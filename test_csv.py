# import pandas as pd
# from langchain_core.documents import Document
# from pathlib import Path
# from langchain_text_splitters import RecursiveCharacterTextSplitter
# from dotenv import load_dotenv
# load_dotenv()



# BASE_DIR = Path(__file__).resolve().parent.parent
# # DATA_PATH = BASE_DIR / "data" / "property_listings.csv"
# DATA_PATH = "data/property_listings_uk.csv"
# PROPERTY_CACHE = {}
# from langchain_qdrant import QdrantVectorStore
# from qdrant_client import QdrantClient
# import os
# from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI


# COLLECTION_NAME = "house_listings"
# EMBEDDING_MODEL = "models/gemini-embedding-001"

# # Initialize embeddings
# embeddings = GoogleGenerativeAIEmbeddings(
#     model=EMBEDDING_MODEL,
#     google_api_key=os.getenv("GOOGLE_API_KEY")
# )

# client = QdrantClient(
#     url="https://5413868d-cca6-4f3e-8aa2-32e74dc78bd1.us-west-1-0.aws.cloud.qdrant.io",
#     api_key=os.getenv("QDRANT_API_KEY"),
#     timeout=60
# )

# vector_store = QdrantVectorStore(
#     client=client,
#     collection_name=COLLECTION_NAME,
#     embedding=embeddings
# )


# def load_csv_to_qdrant(DATA_PATH, client_id):
#     df = pd.read_csv(DATA_PATH)

#     documents = []

#     for _, row in df.iterrows():
#         content = f"""
#         Property_id: {row['property_id']}
#         Title: {row['title']}
#         Description: {row['description']}
#         Price: {row['price_usd']}
#         Area_sqft: {row['area_sqft']}
#         Location: {row['location']}
#         Bedrooms: {row['bedrooms']}
#         Bathrooms: {row['bathrooms']}
#         Property_type: {row['property_type']}
#         Amenities: {row['amenities']}
#         Listing_date: {row['listing_date']}
#         image_url: {row['image_url']}
#         """
        
#         metadata = {
#             "client_id": client_id,
#             "property_id": row["property_id"],
#             "title": row["title"],
#             "price_usd": row["price_usd"],
#             "location": row["location"],
#             "bedrooms": row["bedrooms"],
#             "bathrooms": row["bathrooms"],
#             "area_sqft": row["area_sqft"],
#             "property_type": row["property_type"],
#             "image_url": row["image_url"],  
            
#         }
#         # PROPERTY_CACHE[row["property_id"]]
        
#         # PROPERTY_CACHE[f"{row["client_id"]}_{row['property_id']}"] = metadata
#         # PROPERTY_CACHE[f"{row['client_id']}_{row['property_id']}"] = metadata
#         client_id = client_id
#         property_id = row["property_id"]

#         PROPERTY_CACHE[f"{client_id}_{property_id}"] = metadata

#         documents.append(Document(page_content=content, metadata=metadata))


#     splitter = RecursiveCharacterTextSplitter(
#         chunk_size=1000,
#         chunk_overlap=200
#     )

#     split_docs = splitter.split_documents(documents)
#     # vector_store.add_documents(docs)
#     batch_size = 10

#     for i in range(0, len(split_docs), batch_size):
#         batch = split_docs[i:i + batch_size]
        
#         vector_store.add_documents(batch)
#     # vector_store.add_documents(documents)

# load_csv_to_qdrant(DATA_PATH, "client_002")

# # print(f"Indexed {len(documents)} properties into Qdrant")