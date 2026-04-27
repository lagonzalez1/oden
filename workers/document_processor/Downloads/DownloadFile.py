import io
import json
import fitz  # PyMuPDF
import aiohttp
from typing import Dict, Any, Optional

class DownloadFile:
    """
        Donwload pdf file handler class
    """
    def __init__(self, body: Any):
        # 1. Handle body parsing (Dict vs JSON String)
        if isinstance(body, dict):
            self.data = body
        else:
            self.data = json.loads(body)
        
        self.doc_id = self.data.get('doc_id')
        self.filing_year = self.data.get('filing_year')
        self.url = f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{self.filing_year}/{self.doc_id}.pdf"
        self._pdf_bytes: Optional[bytes] = None

    async def get_pdf(self, timeout: int = 10) -> Optional[bytes]:
        """Downloads the PDF and stores it in memory."""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(self.url, timeout=timeout) as response:
                    if response.status in [200, 304]:
                        self._pdf_bytes = await response.read()
                        return self._pdf_bytes
                    else:
                        print(f"Failed to download {self.doc_id}: Status {response.status}")
                        return None
            except Exception as e:
                print(f"Error downloading file {self.doc_id}: {e}")
                return None

    def get_text(self) -> Optional[str]:
        """Extracts plain text from the downloaded PDF bytes."""
        if not self._pdf_bytes:
            print("No PDF content available. Call get_pdf() first.")
            return None
        
        try:
            # fitz.open uses 'stream' for bytes
            with fitz.open(stream=self._pdf_bytes, filetype="pdf") as doc:
                text = "".join([page.get_text() for page in doc])
                return text
        except Exception as e:
            print(f"Error extracting text from {self.doc_id}: {e}")
            return None