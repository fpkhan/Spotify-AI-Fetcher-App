import pandas as pd
import urllib
from Credentials import DB_USER as user, DB_PASSWORD as password
from sqlalchemy import create_engine

server = 'jio-internship-server.database.windows.net'
database = 'SpotifyDB'

connection_string = f'Driver={{ODBC Driver 18 for SQL Server}};Server=tcp:{server},1433;Database={database};Uid={user};Pwd={password};Encrypt=yes;TrustServerCertificate=no;Connection Timeout=50;'
params = urllib.parse.quote_plus(connection_string)

engine = create_engine(f'mssql+pyodbc:///?odbc_connect={params}')


print("Top 10 rows of the CSV file:")
query = '''SELECT TOP 10 name, artists, popularity 
FROM track_data 
ORDER BY popularity DESC'''

df = pd.read_sql(query, con=engine)
print(df)