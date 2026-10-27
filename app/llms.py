from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from app.config import GEMINI_API_KEY, GROQ_API_KEY

MODELOS= {
    "gemini":ChatGoogleGenerativeAI(api_key=GEMINI_API_KEY,
                                  model="gemini-3.6-flash",
                                  temperature=0),
    "groq": ChatGroq(api_key=GROQ_API_KEY,
                    model="qwen/qwen3.8-27b",
                    temperature=0,
                    reasoning_format="hidden",
                    reasoning_effort="none",
                    max_tokens=512),
    "rapido": ChatGroq(api_key=GROQ_API_KEY,
                        model="qwen/qwen3.8-27b",
                        temperature=0.7,
                        reasoning_format="hidden",
                        reasoning_effort="none",
                        max_tokens=512)
}

# Aliases para app/observabilidade.py, que prende um callback de medição
# nesses três objetos — os mesmos usados por llm_especialista abaixo (não
# são cópias), então o fallback Gemini -> Groq fica coberto também.
llm_gemini = MODELOS["gemini"]
llm_groq   = MODELOS["groq"]

# Se o gemini falhar , o GroqAssume
llm_especialista = MODELOS["gemini"].with_fallbacks([MODELOS["groq"]])

# --- Modelo rápido para tarefas de classificação (roteador, orquestrador) ------
llm_rapido = ChatGroq(
    model="qwen/qwen3.8-27b",
    temperature=0.0,
    api_key=GROQ_API_KEY,
    reasoning_format="hidden",
    reasoning_effort="none",
    max_tokens=512,
)
