from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.database import Base

class Company(Base):
    __tablename__ = "companies"
    
    id = Column(Integer, primary_key=True, index=True)
    figi = Column(String, unique=True, nullable=False, index=True)
    ticker = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    isin = Column(String, nullable=True, index=True)
    sector = Column(String, nullable=True)
    currency = Column(String, nullable=False, default="RUB")
    lot = Column(Integer, nullable=False, default=1)
    api_trade_available_flag = Column(Boolean, default=False)
    
    # Метаданные
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())