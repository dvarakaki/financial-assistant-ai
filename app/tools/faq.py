from langchain.tools import tool
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from app.config import FAQ_PDF_PATH, GEMINI_API_KEY

@tool
def faq_retriever(question: str) -> str:
    """
    Lê o arquivo pdf e retorna a resposta para o usúario.
    """
    # le o pdf
    loader = PyPDFLoader(FAQ_PDF_PATH)
    docs = loader.load()

    # normaliza os caracteres e prerapa o texto
    splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=150)
    chuncks = splitter.split_documents(docs)
    
    # converte as chunks em um vetor numerico
    embeddings = GoogleGenerativeAIEmbeddings(
        model="gemini-embedding-2-preview",
        google_api_key=GEMINI_API_KEY
    )
     
    # armazena os vetores em um indice que busca por similaridade
    db = FAISS.from_documents(chuncks, embeddings)
 
    # busca a pergunta do usuario na rede por similaridade, e pega os seis mais similares
    results = db.similarity_search(question, k=2)

    print(results)

    contexto = "\n\n".join([doc.page_content for doc in results])
    return contexto
