from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Text, BigInteger
import os
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import MetaData

# Database Configuration
# In production, use environment variables
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://bluecoins_user:bluecoins_password@localhost/bluecoins_db")

is_sqlite = DATABASE_URL.startswith("sqlite")

engine_kwargs = {
    "echo": False,
}

if is_sqlite:
    # SQLite does not support asyncpg connection args or postgres pool tuning.
    engine_kwargs["connect_args"] = {}
else:
    engine_kwargs.update(
        {
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "pool_size": 5,
            "max_overflow": 10,
            "connect_args": {"statement_cache_size": 0},
        }
    )

engine = create_async_engine(DATABASE_URL, **engine_kwargs)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
schema_name = os.getenv("DB_SCHEMA") or None
Base = declarative_base(metadata=MetaData(schema=schema_name))

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
    decision_state = Column(String, index=True, nullable=True)  # auto_approved|needs_review|force_review
    decision_reason = Column(Text, nullable=True)
    review_priority = Column(Integer, index=True, nullable=True)
    review_bucket = Column(String, index=True, nullable=True)
    note = Column(Text, nullable=True)
    # ai_reasoning = Column(Text, nullable=True) # DEPRECATED: Moved to AIMemory table



class AIMemory(Base):
    __tablename__ = "ai_memory"
    
    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id", ondelete="SET NULL"))
    pattern_key = Column(String, index=True) # e.g. "SHELL", "UBER"
    
    ai_suggested_category_id = Column(Integer, nullable=True)
    user_selected_category_id = Column(Integer, nullable=True)
    
    ai_reasoning = Column(Text, nullable=True) # Initial reasoning
    reflection = Column(Text, nullable=True) # Post-correction analysis
    policy_version = Column(String, nullable=True)
    threshold_used = Column(Float, nullable=True)
    conflict_flags_json = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    transaction = relationship("Transaction", back_populates="memory_entries")


class MerchantKeywordAlias(Base):
    __tablename__ = "merchant_keyword_aliases"

    id = Column(Integer, primary_key=True, index=True)
    normalized_phrase = Column(String, index=True, nullable=False)
    canonical_keyword = Column(String, index=True, nullable=False)
    support_count = Column(Integer, nullable=False, default=0)
    verified_count = Column(Integer, nullable=False, default=0)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    metadata_json = Column(Text, nullable=True)

class AIGlobalMemory(Base):
    __tablename__ = "ai_global_memory"

    id = Column(Integer, primary_key=True, index=True)
    instruction = Column(Text, nullable=False)
    source = Column(String, default="user_review")
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AICategoryUnderstanding(Base):
    __tablename__ = "ai_category_understanding"

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("categories.id"), unique=True, nullable=False, index=True)
    understanding = Column(Text, nullable=False)
    sample_transactions_json = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
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
    source_transaction_id = Column(Integer, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True)
    prompt = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    transaction = relationship("Transaction", back_populates="finetune_examples")


class CategoryBenchmarkItem(Base):
    __tablename__ = "category_benchmark_items"

    id = Column(Integer, primary_key=True, index=True)
    source_file = Column(String, nullable=True, index=True)
    source_row_number = Column(Integer, nullable=True)
    external_id = Column(String, nullable=True, index=True)

    description = Column(String, nullable=False, index=True)
    amount = Column(Float, nullable=True)
    tx_type = Column(String, nullable=True, index=True)
    date = Column(DateTime, nullable=True, index=True)
    raw_row_json = Column(Text, nullable=True)

    expected_category_id = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)
    expected_parent_name = Column(String, nullable=True)
    expected_category_name = Column(String, nullable=True)
    expected_type = Column(String, nullable=True, index=True)
    label_source = Column(String, nullable=True)

    last_predicted_category_id = Column(Integer, nullable=True)
    last_predicted_type = Column(String, nullable=True)
    last_predicted_confidence = Column(Float, nullable=True)
    last_predicted_reasoning = Column(Text, nullable=True)
    last_evaluated_at = Column(DateTime, nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    expected_category = relationship("Category")


class CategoryBenchmarkRun(Base):
    __tablename__ = "category_benchmark_runs"

    id = Column(Integer, primary_key=True, index=True)
    model = Column(String, nullable=False, index=True)
    total_items = Column(Integer, nullable=False, default=0)
    evaluated_items = Column(Integer, nullable=False, default=0)
    overall_score = Column(Float, nullable=False, default=0.0)  # 0..100
    memory_score = Column(Float, nullable=False, default=0.0)   # 0..100
    memory_coverage = Column(Float, nullable=False, default=0.0)  # 0..100
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

class InteractionLog(Base):
    __tablename__ = "interaction_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    user_id = Column(BigInteger, index=True)
    username = Column(String, nullable=True)
    message_content = Column(Text, nullable=True)
    detected_intent = Column(String, nullable=True, index=True)
    confidence_score = Column(Float, nullable=True)
    entities_json = Column(Text, nullable=True)
    action_taken = Column(String, nullable=True)
    response_content = Column(Text, nullable=True)


class OperationLog(Base):
    __tablename__ = "operation_logs"

    id = Column(Integer, primary_key=True, index=True)
    operation_type = Column(String, nullable=False, index=True)  # import_batch|review_action
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    undone_at = Column(DateTime, nullable=True, index=True)

# Add relationships to Transaction
Transaction.memory_entries = relationship("AIMemory", back_populates="transaction", cascade="save-update, merge")
Transaction.finetune_examples = relationship("LLMFineTuneExample", back_populates="transaction", cascade="save-update, merge")

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
