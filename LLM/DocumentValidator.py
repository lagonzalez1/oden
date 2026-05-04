from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import date

class TransactionModel(BaseModel):
    asset_name: str = Field(description="Full name of the asset, e.g., Alphabet Inc Class A")
    ticker: Optional[str] = Field(description="The stock ticker symbol, e.g., GOOGL")
    asset_type: str = Field(description="The bracketed type code, e.g., [ST], [AB], [OP]")
    owner: Optional[str] = Field(description="Who owns the asset: Self, Spouse, or Joint (SP/DC/JT)")
    transaction_type: str = Field(description="P for Purchase, S for Sale, E for Exchange")
    transaction_date: str = Field(description="The date the trade occurred e.g., 01/02/2000")
    notification_date: str = Field(description="The date the filer was notified/filed")
    amount_range: float = Field(description="The dollar cost e.g 5000")
    cap_gains_over_200: bool = Field(default=False)
    description: Optional[str] = Field(description="Raw description text from the filing")
    
    # This field allows the LLM to parse out complex info like strike prices
    metadata: Optional[Dict[str, Any]] = Field(
        description="Extracted key-value pairs from the description, like strike_price, expiration_date, or share_count"
    )

class FilingExtraction(BaseModel):
    filing_id: str = Field(description="The unique ID of the document, e.g., 20033725")
    name: str = Field(description="Full name of the filer")
    status: str = Field(description="Membership status, e.g., Member, Candidate")
    state_district: str = Field(description="The state and district code, e.g., CA11")
    transactions: List[TransactionModel]