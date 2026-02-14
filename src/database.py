from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text
import os
from datetime import datetime

# Database Configuration
# In production, use environment variables
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://bluecoins_user:bluecoins_password@localhost/bluecoins_db")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

class Account(Base):
    __tablename__ = "accounts"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    institution = Column(String) # e.g. HSBC, Wise
    
    transactions = relationship("Transaction", back_populates="account")

class Category(Base):
    __tablename__ = "categories"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String) # e.g. Fuel
    parent_name = Column(String) # e.g. Car
    type = Column(String) # expense or income
    
    # Composite unique constraint on name + parent_name would be ideal
    # but for simplicity we'll handle uniqueness in logic
    
    transactions = relationship("Transaction", back_populates="category")

class Transaction(Base):
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, index=True)
    description = Column(String, index=True)
    amount = Column(Float)
    type = Column(String) # expense, income, transfer
    
    # Foreign Keys
    account_id = Column(Integer, ForeignKey("accounts.id"))
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    
    # Relationships
    account = relationship("Account", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")
    
    # Metadata
    raw_csv_row = Column(Text) # Store original row for debugging
    is_verified = Column(Boolean, default=False) # True if user confirmed category
    confidence_score = Column(Float, nullable=True) # AI Confidence (0.0 - 1.0)
    # ai_reasoning = Column(Text, nullable=True) # DEPRECATED: Moved to AIMemory table



class AIMemory(Base):
    __tablename__ = "ai_memory"
    
    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"))
    pattern_key = Column(String, index=True) # e.g. "SHELL", "UBER"
    
    ai_suggested_category_id = Column(Integer, nullable=True)
    user_selected_category_id = Column(Integer, nullable=True)
    
    ai_reasoning = Column(Text, nullable=True) # Initial reasoning
    reflection = Column(Text, nullable=True) # Post-correction analysis
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    transaction = relationship("Transaction", back_populates="memory_entries")

class AIGlobalMemory(Base):
    __tablename__ = "ai_global_memory"

    id = Column(Integer, primary_key=True, index=True)
    instruction = Column(Text, nullable=False)
    source = Column(String, default="user_review")
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class LLMKnowledgeChunk(Base):
    __tablename__ = "llm_knowledge_chunks"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String, index=True, nullable=False)  # e.g. transaction
    source_id = Column(Integer, index=True, nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    embedding_model = Column(String, nullable=False)
    embedding_vector = Column(Text, nullable=False)  # JSON serialized list[float]
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class LLMSkill(Base):
    __tablename__ = "llm_skills"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    description = Column(Text, nullable=True)
    instruction = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    priority = Column(Integer, default=100, nullable=False)  # lower means earlier in prompt
    created_at = Column(DateTime, default=datetime.utcnow)


class LLMFineTuneExample(Base):
    __tablename__ = "llm_finetune_examples"

    id = Column(Integer, primary_key=True, index=True)
    source_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=False)
    prompt = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

# Add back_populates to Transaction
Transaction.memory_entries = relationship("AIMemory", back_populates="transaction", cascade="all, delete-orphan")

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
