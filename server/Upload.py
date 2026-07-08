import pandas as pd
import urllib
from Credentials import DB_USER as user, DB_PASSWORD as password
from sqlalchemy import create_engine

server = 'jio-internship-server.database.windows.net'
database = 'SpotifyDB'

connection_string = f'Driver={{ODBC Driver 18 for SQL Server}};Server=tcp:{server},1433;Database={database};Uid={user};Pwd={password};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;'
params = urllib.parse.quote_plus(connection_string)

engine = create_engine(f'mssql+pyodbc:///?odbc_connect={params}', fast_executemany=True)
#conn = engine.connect()


print("Reading CSV file...")
df = pd.read_csv('data/tracks.csv')

print("Uploading rows to Azure SQL Database...")
table_name = 'track_data'
df.to_sql(table_name, 
          engine,
          if_exists='replace', 
          index=False,
          chunksize=10000)

print("Data uploaded successfully to Azure SQL Database")
