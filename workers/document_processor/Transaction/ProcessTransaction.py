import logging
import uuid
from typing import Dict, Optional, Any, List
from datetime import datetime
from YFinance.ProcessFinancials import ProcessFinancials
from Service.document_service import DocumentsService
from Service.member_service import MemberService
from Service.graph_service import GraphService
from Service.commitee_service import CommitteeService
from Service.stock_service import StockService


logger = logging.getLogger(__name__)


class ProcessTransaction:
    """
    Handles transaction processing after successful document extraction.
    Processes filing content, calculates financial performance, and saves to databases.
    """

    def __init__(
        self,
        document_service: DocumentsService,
        member_service: MemberService,
        neo4j_service: GraphService,
        committee_service: CommitteeService,
        stock_service: StockService
    ):
        self.document_service = document_service
        self.neo4j_service = neo4j_service
        self.committee_service = committee_service
        self.stock_service = stock_service
        self.member_service = member_service

    async def process_and_save(
        self,
        doc_id: str,
        content: Dict[str, Any],
        doc_size: Optional[int] = None
    ) -> bool:
        """
        Main entry point for processing extracted filing content.
        
        Args:
            doc_id: Document ID
            content: Extracted filing content with transactions
            doc_size: Size of the document in characters/bytes
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f"[ProcessTransaction] Starting processing for doc_id: {doc_id}")
            logger.info(f"[ProcessTransaction] Content: {content}")

            if await self._is_document_processed(doc_id):
                logger.info(f"[ProcessTransaction] Document {doc_id} has already been processed: Skipping")
                return True
            
            # Step 2: Extract unique stock information {ticker: stock_data}
            stocks_by_ticker = await self._extract_stock_data(content)

            # Step 3: Save stock master data (with upsert)
            if stocks_by_ticker:
                await self._save_stock_data(stocks_by_ticker)

            legislator = await self._find_legislator(
                content.get("first_name"),
                content.get("last_name"),
                content.get("state_district"),
            )
            logger.info(f"[ProcessTransaction] Legislator: {legislator}")

            if legislator:
                bioguide_id = legislator["bioguide_id"]
                content["bioguide_id"] = bioguide_id
                content["filing_id"] = doc_id
                content["full_name"] = (
                    content.get("full_name")
                    or legislator.get("official_full")
                    or f"{content.get('first_name', '')} {content.get('last_name', '')}".strip()
                )
                content["status"] = content.get("status") or "Member"
                if not content.get("state_district") and legislator.get("state"):
                    district = legislator.get("district") or ""
                    content["state_district"] = f"{legislator['state']}{district}"

                await self._enrich_transactions_with_similarity(
                    content=content,
                    stocks_by_ticker=stocks_by_ticker or {},
                    bioguide_id=bioguide_id,
                )
                await self._ingest_to_graph(content)

            await self._update_document_status(doc_id, doc_size, success=True)

            logger.info(f"[ProcessTransaction] Successfully processed doc_id: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"[ProcessTransaction] Failed to process doc_id {doc_id}: {e}")
            await self._update_document_status(doc_id, doc_size, success=False)
            return False

    async def _enrich_transactions_with_similarity(
        self,
        content: Dict[str, Any],
        stocks_by_ticker: Dict[str, Dict[str, Any]],
        bioguide_id: str,
    ) -> None:
        """Score each tx's asset description against the member's committee chunks."""
        similarity_cache: Dict[str, Optional[Dict[str, Any]]] = {}

        for tx in content.get("transactions", []):
            ticker = tx.get("ticker")
            if not ticker:
                continue

            if ticker not in similarity_cache:
                stock = stocks_by_ticker.get(ticker) or {}
                description = stock.get("description")
                if not description:
                    logger.warning(
                        f"[ProcessTransaction] No description for {ticker}; skipping similarity"
                    )
                    similarity_cache[ticker] = None
                else:
                    matches = await self.committee_service.compare_description_to_committee_chunks(
                        description=description,
                        bioguide_id=bioguide_id,
                        limit=1,
                    )
                    similarity_cache[ticker] = matches[0] if matches else None
                    logger.info(
                        f"[ProcessTransaction] Similarity for {ticker}: {similarity_cache[ticker]}"
                    )

            best = similarity_cache[ticker]
            if best:
                tx["committee_relevance_score"] = float(best["similarity"])
                tx["matched_committee_id"] = str(best["committee_id"])
                tx["matched_committee_name"] = best.get("committee_title")
                tx["relevance_method"] = "committee_chunk_embedding"
            else:
                tx["committee_relevance_score"] = None
                tx["matched_committee_id"] = None
                tx["matched_committee_name"] = None
                tx["relevance_method"] = None

    async def _is_document_processed(self, doc_id: str) -> bool:
        """
        Check if the document has already been processed.
        """
        try:
            document = await self.document_service.get_document_by_id(doc_id)
            return document
        except Exception as e:
            logger.error(f"[ProcessTransaction] Failed to check if document is processed: {e}")

    async def _extract_stock_data(self, content: Dict[str, Any]) -> Optional[Dict[str, Dict[str, Any]]]:
        """
        Extract unique stock information from filing content.
        Returns all stock data (from DB or YFinance), but only fetches from YFinance if not in DB.
        
        Args:
            content: Filing content with transactions
            
        Returns:
            Dict keyed by ticker -> stock data (mix of existing DB records and newly fetched)
        """
        try:
            all_stock_data: Dict[str, Dict[str, Any]] = {}
            stocks_to_fetch = []

            # Get unique tickers from transactions
            for tx in content.get("transactions", []):
                ticker = tx.get("ticker")
                if not ticker or ticker in all_stock_data or ticker in stocks_to_fetch:
                    continue
                
                # Check if stock already exists in database
                existing_stock = await self.stock_service.get_stock_by_ticker(ticker)
                
                if existing_stock:
                    all_stock_data[ticker] = existing_stock
                    logger.info(f"[ProcessTransaction] Stock {ticker} found in DB")
                else:
                    stocks_to_fetch.append(ticker)
                    logger.info(f"[ProcessTransaction] Stock {ticker} not in DB, will fetch from YFinance")

            # Fetch missing stocks from YFinance
            if stocks_to_fetch:
                processor = ProcessFinancials(content)
                yfinance_stock_data = await processor.process_stock_data()
                
                if yfinance_stock_data:
                    for stock in yfinance_stock_data:
                        ticker = stock.get('ticker')
                        if ticker in stocks_to_fetch:
                            all_stock_data[ticker] = stock
                    
                    logger.info(f"[ProcessTransaction] Fetched {len(yfinance_stock_data)} stocks from YFinance")
                else:
                    logger.warning("[ProcessTransaction] No stock data extracted from YFinance")
            
            logger.info(f"[ProcessTransaction] Total stocks ready: {len(all_stock_data)}")
            return all_stock_data if all_stock_data else None

        except Exception as e:
            logger.error(f"[ProcessTransaction] Failed to extract stock data: {e}")
            return None


    async def _find_legislator(self, first_name: str, last_name: str, state_district: str) -> Dict[str, Any]:
        """
        Find legislator in the database.
        """
        try:
            legislator = await self.member_service.get_legislator_by_name(first_name=first_name, last_name=last_name, state_district=state_district)
            return legislator
        except Exception as e:
            logger.error(f"[ProcessTransaction] Failed to find legislator: {e}, first_name: {first_name}, last_name: {last_name}, state_district: {state_district}")


    async def _save_stock_data(self, stock_data: Dict[str, Dict[str, Any]]) -> bool:
        """
        Save or update stock master data in the database.
        Only inserts stocks that don't already exist (skips DB records).
        
        Args:
            stock_data: Dict keyed by ticker -> stock data (mix of DB and new records)
            
        Returns:
            bool: True if successful
        """
        try:
            stocks_to_insert = []
            
            for ticker, stock in stock_data.items():
                existing = await self.stock_service.get_stock_by_ticker(ticker)
                
                if not existing:
                    stocks_to_insert.append(stock)
                    logger.info(f"[ProcessTransaction] Will insert stock {ticker}")
                else:
                    logger.info(f"[ProcessTransaction] Stock {ticker} already in DB, skipping insert")
            
            if stocks_to_insert:
                await self.stock_service.create_stocks(stocks_to_insert)
                logger.info(f"[ProcessTransaction] Inserted {len(stocks_to_insert)} new stocks to database")
            else:
                logger.info("[ProcessTransaction] No new stocks to insert")
                
            return True

        except Exception as e:
            logger.error(f"[ProcessTransaction] Failed to save stock data: {e}")
            return False



    async def _update_document_status(
        self,
        doc_id: str,
        doc_size: Optional[int],
        success: bool = True
    ) -> bool:
        """
        Update document extraction status in the database.
        
        Args:
            doc_id: Document ID
            doc_size: Size of the document
            success: Whether processing was successful
            
        Returns:
            bool: True if successful
        """
        try:
            status = "SUCCESS" if success else "FAILED"
            update = {
                'doc_id_parsed': success,
                'processed_status': status,
                'last_updated_date': datetime.now(),
                'doc_size': doc_size
            }
            
            await self.document_service.update_extractions(doc_id, update)
            logger.info(f"[ProcessTransaction] Updated document status to {status} for doc_id: {doc_id}")
            return True

        except Exception as e:
            logger.error(f"[ProcessTransaction] Failed to update document status: {e}")
            return False

    async def _ingest_to_graph(self, content: Dict[str, Any]) -> bool:
        """
        Ingest filing data into Neo4j graph database.
        
        Args:
            content: Filing content with transactions and legislator info
            
        Returns:
            bool: True if successful
        """
        try:
            await self.neo4j_service.ingest_filing(content)
            logger.info("[ProcessTransaction] Successfully ingested filing to Neo4j graph")
            return True

        except Exception as e:
            logger.error(f"[ProcessTransaction] Failed to ingest to graph: {e}")
            return False

    async def mark_extraction_failed(self, doc_id: str) -> bool:
        """
        Mark a document extraction as failed.
        
        Args:
            doc_id: Document ID
            
        Returns:
            bool: True if successful
        """
        return await self._update_document_status(doc_id, doc_size=None, success=False)


