
import ollama
from sqlalchemy import text
from src.database import get_db, AsyncSessionLocal

class FinanceChatAI:
    def __init__(self, model="llama3.2:3b"):
        self.client = ollama.AsyncClient()
        self.model = model
        
        # Schema for the LLM
        self.schema = """
Table: transactions
Columns: id (int), date (datetime), description (string), amount (float), type (string: 'expense'/'income'), category_id (int), account_id (int), is_verified (bool)

Table: categories
Columns: id (int), name (string), parent_name (string), type (string)

Table: accounts
Columns: id (int), name (string), institution (string)

Relationships:
transactions.category_id -> categories.id
transactions.account_id -> accounts.id
"""

    async def chat(self, user_question, session):
        """
        1. Generate SQL
        2. Execute SQL
        3. Explain Result
        """
        
        # 1. Generate SQL
        sql_query = await self._generate_sql(user_question)
        if not sql_query:
            return "Sorry, I couldn't understand that question well enough to query the database."
            
        if "DELETE" in sql_query.upper() or "UPDATE" in sql_query.upper() or "DROP" in sql_query.upper():
            return "I cannot execute modification queries for safety reasons."

        # 2. Execute SQL
        try:
            print(f"DEBUG: Executing SQL: {sql_query}")
            result = await session.execute(text(sql_query))
            rows = result.fetchall()
            columns = result.keys()
            
            data_str = self._format_results(columns, rows)
            
        except Exception as e:
            return f"Error executing query: {e}\nQuery was: {sql_query}"

        # 3. Summarize
        answer = await self._summarize(user_question, sql_query, data_str)
        return answer

    async def _generate_sql(self, question):
        prompt = f"""
You are a PostgreSQL expert.
Convert the user's question into a SQL query based on the schema below.

Schema:
{self.schema}

Rules:
1. Return ONLY the SQL query. No markdown, no explanation.
2. Use ILIKE for string matching.
3. For 'last month', 'this year' etc, use PostgreSQL date functions (e.g. CURRENT_DATE).
4. Join tables when names are needed (e.g. category name).

User Question: {question}
SQL:
"""
        try:
            response = await self.client.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            content = response['message']['content'].strip()
            # Cleanup markdown if present
            content = content.replace("```sql", "").replace("```", "").strip()
            return content
        except Exception as e:
            print(f"Error generating SQL: {e}")
            return None

    def _format_results(self, columns, rows):
        if not rows:
            return "No results found."
        
        # Simple string representation
        # Header
        res = [ " | ".join(columns) ]
        # Rows
        for row in rows:
            res.append(" | ".join(str(item) for item in row))
            
        return "\n".join(res)

    async def _summarize(self, question, query, data):
        prompt = f"""
User Question: {question}
SQL Query Used: {query}
Data Result:
{data}

Task: Answer the user's question based on the Data Result. Be concise and friendly.
If the data is empty, say so.
"""
        try:
            response = await self.client.chat(model=self.model, messages=[
                {'role': 'user', 'content': prompt}
            ])
            return response['message']['content'].strip()
        except Exception as e:
            return f"Result: {data} (Error summarizing: {e})"
