# LocalScript — Architecture Diagrams

---

## 1. C4 Level 1 — System Context

```mermaid
C4Context
    title System Context — LocalScript

    Person(user, "Developer / Пользователь", "Описывает задачу на естественном языке (RU/EN), получает Lua-код")

    System(localscript, "LocalScript", "AI-сервис генерации Lua-кода для платформы MWS Octapi LowCode")

    System_Ext(octapi, "MWS Octapi LowCode", "Целевая платформа, в которой исполняется сгенерированный Lua-код")

    Rel(user, localscript, "Prompt → Lua-код", "HTTP REST API :18080")
    Rel(user, octapi, "Вставляет сгенерированный Lua-код")
```

---

## 2. C4 Level 2 — Container Diagram

```mermaid
C4Container
    title Container Diagram — LocalScript

    Person(user, "Developer")

    Container_Boundary(system, "LocalScript System") {
        Container(backend, "Backend API", "Python / FastAPI / Uvicorn", "REST API, маршрутизация запросов, управление чат-сессиями")
        Container(pipeline, "Agent Pipeline", "Python module", "Оркестрация: RAG → LLM → Extract → Validate → Fix loop")
        Container(chatstore, "Chat Store", "JSON files on disk", "Хранение сессий и истории сообщений (chat_storage/)")
        ContainerDb(qdrant, "Qdrant", "Vector DB", "Хранение эмбеддингов базы знаний Lua-домена")
        Container(ollama, "Ollama", "LLM Inference Server", "Локальная модель qwen2.5-coder:7b для генерации кода")
        Container(lua, "Lua 5.4 Runtime", "luac / lua", "Синтаксическая валидация сгенерированного Lua-кода")
        Container(init, "Init Service", "Python script", "Индексация knowledge base в Qdrant, pull модели Ollama")
    }

    Rel(user, backend, "HTTP POST/GET", ":18080")
    Rel(backend, pipeline, "run(prompt, history)")
    Rel(backend, chatstore, "create/read/write sessions")
    Rel(pipeline, qdrant, "Semantic search (retrieve)", "HTTP :6333")
    Rel(pipeline, ollama, "LLM chat completion", "HTTP :11434")
    Rel(pipeline, lua, "Syntax check", "subprocess stdin/stdout")
    Rel(init, qdrant, "Index knowledge", "HTTP :6333")
    Rel(init, ollama, "Pull model", "HTTP :11434")
```

---

## 3. Agent Pipeline — Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant API as FastAPI Backend
    participant P as AgentPipeline
    participant RAG as RAG Module<br/>(SentenceTransformer + Qdrant)
    participant LLM as Ollama LLM<br/>(qwen2.5-coder:7b)
    participant V as Lua Validator<br/>(luac)

    U->>API: POST /generate {prompt}<br/>или POST /chat/sessions/{id}/messages {content}
    API->>P: pipeline.run(prompt, chat_history)

    rect rgb(240, 248, 255)
        Note over P,RAG: Retrieval-Augmented Generation
        P->>RAG: retrieve(user_query, top_k=3)
        RAG->>RAG: encode(query) → vector
        RAG-->>P: context_chunks[]
        P->>P: _build_system_prompt()<br/>SYSTEM_PROMPT + RAG context
    end

    rect rgb(255, 250, 240)
        Note over P,LLM: Code Generation
        P->>LLM: POST /api/chat {messages, model, options}
        LLM-->>P: response_text
    end

    alt Response is clarifying question
        P-->>API: PipelineResult(is_question=true)
        API-->>U: {message: "Уточните...", is_question: true}
    else Response contains Lua code
        P->>P: extract_lua_code() / fallback_extract()<br/>+ clean_code()

        rect rgb(240, 255, 240)
            Note over P,V: Validation + Self-Fix Loop (max 2 iterations)
            P->>V: validate_lua(code)
            V-->>P: ValidationResult

            loop is_valid == false && iterations < 3
                P->>P: Build FIX_PROMPT_TEMPLATE
                P->>LLM: POST /api/chat {messages + fix prompt}
                LLM-->>P: fixed response_text
                P->>P: extract + clean
                P->>V: validate_lua(code)
                V-->>P: ValidationResult
            end
        end

        P-->>API: PipelineResult(code, is_valid, iterations)
        API-->>U: {code: "...", is_valid: true/false, iterations: N}
    end
```

---

## 4. Backend — Component Diagram

```mermaid
flowchart TB
    subgraph CLIENT["Client"]
        user(("User / HTTP Client"))
    end

    subgraph BACKEND["FastAPI Backend  (:18080)"]
        direction TB

        subgraph ROUTES["API Endpoints"]
            r1["POST /generate"]
            r2["POST /chat/sessions"]
            r3["GET  /chat/sessions"]
            r4["GET  /chat/sessions/{id}/messages"]
            r5["POST /chat/sessions/{id}/messages"]
        end

        subgraph SCHEMAS["Pydantic Schemas"]
            s1["GenerateRequest"]
            s2["GenerateResponse"]
            s3["SessionCreateOut"]
            s4["SessionOut"]
            s5["MessageIn"]
            s6["MessageOut"]
        end

        subgraph AGENT["Agent Module"]
            direction TB
            AP["AgentPipeline"]
            PR["Prompts<br/>(SYSTEM_PROMPT, FIX_PROMPT)"]
            RAG["RAG<br/>(retrieve / index_knowledge)"]
            VAL["Validator<br/>(validate_lua)"]
            EMBED["SentenceTransformer<br/>paraphrase-multilingual-MiniLM-L12-v2"]
        end

        subgraph STORAGE["Chat Storage"]
            CS["ChatStore"]
            SD["SessionData"]
            MD["MessageData"]
            FS[("JSON Files<br/>chat_storage/*.json")]
        end

        CFG["Config<br/>(pydantic-settings + .env)"]
    end

    subgraph INFRA["Infrastructure"]
        QDRANT[("Qdrant<br/>Vector DB :6333")]
        OLLAMA["Ollama<br/>LLM Server :11434"]
        LUA["Lua 5.4<br/>luac binary"]
    end

    user --> r1 & r5
    user --> r2 & r3 & r4

    r1 --> AP
    r5 --> AP
    r5 --> CS

    r2 --> CS
    r3 --> CS
    r4 --> CS

    AP --> PR
    AP --> RAG
    AP --> VAL
    RAG --> EMBED
    RAG --> QDRANT

    AP -->|"HTTP /api/chat"| OLLAMA
    VAL -->|"subprocess"| LUA

    CS --> SD & MD
    SD --> FS
    MD --> FS

    CFG -.->|settings| AP & CS & RAG

    style CLIENT fill:#e8f4fd,stroke:#4a90d9
    style BACKEND fill:#fff,stroke:#333,stroke-width:2px
    style ROUTES fill:#e8f5e9,stroke:#4caf50
    style SCHEMAS fill:#fff3e0,stroke:#ff9800
    style AGENT fill:#f3e5f5,stroke:#9c27b0
    style STORAGE fill:#fce4ec,stroke:#e91e63
    style INFRA fill:#f5f5f5,stroke:#666
```

---

## 5. Docker Compose — Deployment Diagram

```mermaid
flowchart LR
    subgraph DOCKER["Docker Compose"]
        direction TB

        subgraph net["Docker Network"]
            QDRANT["🗄 qdrant<br/>qdrant/qdrant:latest<br/>:6333"]
            OLLAMA["🤖 ollama<br/>ollama/ollama:latest<br/>:11434<br/>(GPU NVIDIA)"]
            INIT["⚙️ init<br/>python -m scripts.init<br/>(run-once)"]
            BACK["🚀 backend<br/>uvicorn app.main:app<br/>:18080"]
        end

        subgraph vols["Volumes"]
            V1[("qdrant_data")]
            V2[("ollama_data")]
            V3[("chat_data")]
        end
    end

    QDRANT --- V1
    OLLAMA --- V2
    INIT --- V3
    BACK --- V3

    INIT -->|"depends_on: healthy"| QDRANT
    INIT -->|"depends_on: healthy"| OLLAMA
    BACK -->|"depends_on: healthy"| QDRANT
    BACK -->|"depends_on: healthy"| OLLAMA
    BACK -->|"depends_on: completed"| INIT

    EXT(("External<br/>:18080")) --> BACK

    style DOCKER fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
    style net fill:#fff,stroke:#999
    style vols fill:#f9fbe7,stroke:#827717
```
