import asyncio
import json
import os
from sqlalchemy import select
from src.database import init_db, get_db, Account, Category, MappingRule, AsyncSessionLocal

async def load_json(filename):
    if not os.path.exists(filename):
        return {}
    with open(filename, 'r') as f:
        return json.load(f)

async def migrate():
    print("Initializing database...")
    await init_db()
    
    async with AsyncSessionLocal() as session:
        # 1. Migrate Accounts
        print("Migrating accounts...")
        accounts_data = await load_json("data/accounts.json")
        # accounts.json is a list of strings ["HSBC", "Wise"]
        for account_name in accounts_data:
            # check if exists
            result = await session.execute(select(Account).where(Account.name == account_name))
            if not result.scalar_one_or_none():
                session.add(Account(name=account_name, institution=account_name))
        
        await session.commit()
        
        # 2. Migrate Categories
        print("Migrating categories...")
        categories_data = await load_json("data/categories.json")
        # Structure: {"Template": {"expense": {"Parent": ["Child"]}, "income": ...}}
        
        category_map = {} # (parent, name) -> id
        
        for template, types in categories_data.items():
            for type_name, parents in types.items():
                for parent, children in parents.items():
                    # Insert Parent Category (if it doesn't exist as a top-level category? No, Bluecoins just has parent field)
                    # Actually Bluecoins has a flat list where some are parents.
                    # But here we model as (Name, ParentName).
                    # Let's insert children directly with their parent_name.
                    
                    for child in children:
                        # Check if exists
                        stmt = select(Category).where(
                            Category.name == child,
                            Category.parent_name == parent,
                            Category.type == type_name
                        )
                        result = await session.execute(stmt)
                        existing = result.scalar_one_or_none()
                        
                        if not existing:
                            cat = Category(name=child, parent_name=parent, type=type_name)
                            session.add(cat)
                            await session.flush() # to get ID
                            category_map[(parent, child)] = cat.id
                        else:
                            category_map[(parent, child)] = existing.id
        
        await session.commit()
        
        # 3. Migrate Mapping Rules
        print("Migrating mapping rules...")
        mapping_data = await load_json("data/category_mapping.json")
        # Structure: "Description": {"parent_category": "X", "category": "Y"}
        
        for description, cat_info in mapping_data.items():
            parent = cat_info.get("parent_category")
            child = cat_info.get("category")
            
            if not parent or not child:
                continue
                
            # Find category ID
            cat_id = category_map.get((parent, child))
            
            # If not found in map (maybe it wasn't in categories.json but appeared in mapping),
            # we should look it up in DB or insert it.
            # For simplicity, let's try to find it in DB ignoring type if not in map
            if not cat_id:
                # Try to find any category with this name/parent
                stmt = select(Category).where(
                    Category.name == child,
                    Category.parent_name == parent
                )
                result = await session.execute(stmt)
                existing = result.first() # take first match
                if existing:
                    cat_id = existing[0].id
                else:
                    # Create it with default type 'expense' (safest bet)
                    print(f"Creating missing category from mapping: {parent} -> {child}")
                    new_cat = Category(name=child, parent_name=parent, type="expense")
                    session.add(new_cat)
                    await session.flush()
                    cat_id = new_cat.id
            
            # Insert MappingRule
            stmt = select(MappingRule).where(MappingRule.keyword == description)
            result = await session.execute(stmt)
            if not result.scalar_one_or_none():
                session.add(MappingRule(keyword=description, category_id=cat_id))
        
        await session.commit()
        print("Migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate())
