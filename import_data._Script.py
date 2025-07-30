import pandas as pd
from sqlalchemy import create_engine, text
import pymysql
import re
from tqdm import tqdm  # For progress bar

# MySQL connection details
host = "localhost"
user = "root"
password = "Bobby$Data123"
database = "pizza"
table_name = "pizza_orders"
csv_file = "D:/POWERBI-PROJECTS/Pizza sales/pizza_sales.csv"
chunksize = 1000  # Optimal chunk size for performance

def clean_column_names(df):
    """Remove all numeric suffixes from column names (like _m0, _m1)"""
    return df.rename(columns=lambda x: re.sub(r'(_m\d+)$', '', x))

def validate_data_lengths(df):
    """Ensure string data fits in database columns"""
    max_lengths = {
        'pizza_size': 1,       # S, M, L, etc.
        'pizza_category': 20,  # Classic, Veggie, etc.
        'pizza_name': 50,      # The Classic Deluxe Pizza
        'pizza_name_id': 20,   # classic_dlx_l
        'pizza_ingredients': 200  # Ingredient lists
    }
    
    for col, max_len in max_lengths.items():
        if col in df.columns:
            df[col] = df[col].astype(str).str.slice(0, max_len)
    return df

# Create SQLAlchemy engine with optimized settings
engine = create_engine(
    f"mysql+pymysql://{user}:{password}@{host}/{database}",
    connect_args={
        'connect_timeout': 10,
        'charset': 'utf8mb4'
    },
    pool_pre_ping=True,
    pool_recycle=3600
)

# First verify the table structure exists
try:
    with engine.connect() as conn:
        # Create table if it doesn't exist (adjust schema as needed)
        conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            pizza_id INT,
            order_id INT,
            pizza_name_id VARCHAR(20),
            quantity INT,
            order_date DATE,
            order_time TIME,
            unit_price DECIMAL(10,2),
            total_price DECIMAL(10,2),
            pizza_size VARCHAR(1),
            pizza_category VARCHAR(20),
            pizza_ingredients VARCHAR(200),
            pizza_name VARCHAR(50),
            PRIMARY KEY (pizza_id)
        )
        """))
        conn.commit()
except Exception as e:
    print(f"Error creating table: {e}")
    exit()

# Read and insert data in chunks
success_count = 0
error_count = 0
total_rows = sum(1 for _ in open(csv_file, 'r', encoding='utf-8')) - 1  # Count rows in CSV

with tqdm(total=total_rows, desc="Importing data") as pbar:
    for i, chunk in enumerate(pd.read_csv(csv_file, chunksize=chunksize)):
        try:
            # Clean column names first
            chunk = clean_column_names(chunk)
            
            # Ensure proper data types
            numeric_cols = ['pizza_id', 'order_id', 'quantity', 'unit_price', 'total_price']
            for col in numeric_cols:
                chunk[col] = pd.to_numeric(chunk[col], errors='coerce')
            
            # Convert date and time formats
            chunk['order_date'] = pd.to_datetime(
                chunk['order_date'], 
                format='%d-%m-%Y', 
                errors='coerce'
            ).dt.strftime('%Y-%m-%d')
            
            chunk['order_time'] = pd.to_datetime(
                chunk['order_time'],
                format='%H:%M:%S',
                errors='coerce'
            ).dt.strftime('%H:%M:%S')
            
            # Validate string lengths
            chunk = validate_data_lengths(chunk)
            
            # Drop rows with invalid data
            required_cols = ['pizza_id', 'order_id', 'order_date', 'order_time', 
                            'unit_price', 'total_price', 'pizza_size']
            chunk = chunk.dropna(subset=required_cols)
            
            if len(chunk) == 0:
                pbar.update(chunksize)
                continue
            
            # Insert data with optimized method
            chunk.to_sql(
                name=table_name,
                con=engine,
                if_exists='append',
                index=False,
                method='multi',
                chunksize=500
            )
            
            success_count += len(chunk)
            pbar.update(len(chunk))
            
        except Exception as e:
            error_count += len(chunk)
            pbar.update(len(chunk))
            print(f"\nError in chunk {i+1}:", str(e)[:500])
            print("First row sample:", chunk.iloc[0].to_dict() if len(chunk) > 0 else "Empty chunk")
            
            # Save problematic chunk for debugging
            chunk.to_csv(f'error_chunk_{i+1}.csv', index=False)
            continue

print("\nImport Summary:")
print(f"Total rows processed: {total_rows}")
print(f"Total rows successfully inserted: {success_count}")
print(f"Total rows failed: {error_count}")
if total_rows > 0:
    print(f"Success rate: {success_count/total_rows*100:.2f}%")

# Verify counts using proper SQL execution
try:
    with engine.connect() as conn:
        # Use text() for explicit SQL statement
        result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
        total_in_db = result.scalar()
        print(f"\nTotal rows in database: {total_in_db}")
        
        # Additional verification
        result = conn.execute(text(f"SELECT MIN(order_date), MAX(order_date) FROM {table_name}"))
        min_date, max_date = result.fetchone()
        print(f"Date range in database: {min_date} to {max_date}")
        
except Exception as e:
    print("\nError verifying database counts:", str(e))
finally:
    engine.dispose()  # Properly close all connections

print("\nData import process completed.")