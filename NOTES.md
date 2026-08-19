# Ctrl+Teach Rewrite — Lesson Notes

Short reference for everything covered. Newest lesson at the bottom.

---

## L1 — Project setup with `uv`

`uv` replaces pyenv + venv + pip + pip-tools. One tool.

```bash
uv init --bare --python 3.12   # scaffold
uv python pin 3.12             # writes .python-version
uv add fastapi "uvicorn[standard]" pydantic-settings sqlalchemy
uv run uvicorn app.main:app --reload
```

| File | What it is | Commit it? |
|---|---|---|
| `pyproject.toml` | **Intent.** Loose ranges (`fastapi>=0.141.1`). Human-edited. | Yes |
| `uv.lock` | **Receipt.** Exact versions + SHA-256 hashes. Tool-generated, never hand-edit. | Yes |
| `.python-version` | Pins the interpreter for this repo | Yes |
| `.venv/` | The actual installed packages | No |

`uv run X` = "run X inside this project's venv" — no activation step needed.

---

## L2 — FastAPI basics

```python
from fastapi import FastAPI

app = FastAPI(title="ctrl+teach")

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- **ASGI** = the `(scope, receive, send)` contract between uvicorn (the server) and FastAPI (the app). `app` is the ASGI callable — that's what `app.main:app` points at.
- **Starlette** is the real web framework underneath. FastAPI adds validation + auto OpenAPI docs on top.
- FastAPI is essentially **a router + a validator**.
- `def` vs `async def`: a plain `def` handler runs in a threadpool, which is correct for blocking work like SQLAlchemy. **Don't cargo-cult `async`.**
- Free docs at `/docs` while the server runs.

---

## L3 — Config with `pydantic-settings`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Ctrl+teach"
    database_url: str = "sqlite:///./ctrlteach.db"

settings = Settings()
```

**Why not just a `.env` file?** A `.env` file is inert text — *something* has to parse it. The choice is `python-dotenv` + `os.environ` vs this. What this buys you:

1. **Type coercion** — `os.environ` gives you strings, always. Trap: `bool("false")` is `True`.
2. **Fails at boot**, not at 3am when the code path is first hit.
3. **One manifest** — every setting the app has, in one class.
4. **Autocomplete** — `settings.database_url` vs `os.environ["DATBASE_URL"]` (typo = crash).

At one setting the win is small. It pays off at ten, and the moment there's a `SECRET_KEY`.

**Precedence:** real env vars beat `.env` file beat class defaults.

**`model_config`** is a *reserved name* in Pydantic v2 — instructions *about* the model, not a field *in* it. Anything else you write becomes a setting.

**v1 → v2 markers** (for reading old code): `class Config` → `model_config`, `@validator` → `@field_validator`, `.dict()` → `.model_dump()`.

**Files:** `.env` is gitignored (real values). `.env.example` is committed (a template) — un-ignored via `!.env.example`.

---

## L4 — SQLAlchemy 2.0

```python
engine = create_engine(settings.database_url, echo=True)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
```

The four objects:

| Object | What it is |
|---|---|
| **Engine** | Connection pool + SQL dialect. **Lazy** — creating it connects to nothing. |
| **sessionmaker** | A factory. Produces one `Session` per request. |
| **Session** | One **transaction**. Also a unit-of-work and an identity map. |
| **Base** | A registry. Every subclass files its table into `Base.metadata`. |

**`Mapped[int]` is input, not decoration.** The annotation *is* the schema — SQLAlchemy reads it to infer the SQL type and nullability. `Mapped[str]` → `NOT NULL`; `Mapped[str | None]` → nullable.

The two flags:
- **`autoflush=False`** — SQL fires only when you say so, not on surprise reads.
- **`expire_on_commit=False`** — without it, attributes expire after commit and FastAPI raises `DetachedInstanceError` when it tries to serialize a closed-session object.

### Proved live with `echo=True`

1. `init_db()` emitted `CREATE TABLE users (id INTEGER NOT NULL, name VARCHAR(255) NOT NULL, PRIMARY KEY (id))` — derived purely from the annotations. Preceded by `PRAGMA table_info` (the IF-NOT-EXISTS check → **idempotent**).
2. `s.add()` emitted **no SQL**. `INSERT` fired only on `commit()`. `id` wasn't in the INSERT — SQLite assigns it.
3. **Identity map** — two `s.get(User, 1)` calls → **one** SELECT, and `a is b` was `True`.
4. **Change tracking** — `a.name = "changed"` emitted nothing until `commit()`, which then generated an `UPDATE` touching only that column.

Values always go out as `VALUES (?)` — **parameterized**, so SQL injection is structurally impossible.

### ⚠ Known limitation
`create_all` only ever **CREATE**s. It never emits `ALTER TABLE`. Change the model → you must delete `ctrlteach.db`. **Alembic** is the proper fix, later.

---

## L5 — Generators and `yield`

One idea:

- **`return`** — done forever. The function's frame is destroyed.
- **`yield`** — **paused.** The frame stays alive, holding all its local variables, until someone resumes it.

A one-`yield` generator is therefore a **resumable scope**: setup / ⏸ / teardown, with the caller's code running in the gap.

```python
def get_session():
    with SessionLocal() as session:
        yield session          # ⏸ endpoint runs here
    # session closes when resumed
```

Same shape as a `with` block and a pytest fixture.

---

## L6 — Dependency injection (`Depends`)

**You never call `get_session()`. FastAPI calls it for you.**

```python
@app.get("/users/{user_id}")
def read_user(user_id: int, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    return {"id": user.id, "name": user.name}
```

**No parentheses** inside `Depends` — you hand over the *function*, not its result.

Per request, FastAPI does:

```
g = get_session()   →   next(g)  opens session  ⏸
                        read_user() runs
                        next(g)  closes session
```

The two parameters come from totally different places:

| Parameter | Source |
|---|---|
| `user_id: int` | The **URL** — the name matches `{user_id}` in the path. The `int` annotation converts `"1"` → `1` and auto-rejects `/users/abc` with a 422. |
| `session: Session` | The **`Depends`** — nothing to do with the URL. |

**Why bother** instead of a manual `try/finally` in every endpoint:
- No repetition
- `app.dependency_overrides[get_session] = fake` swaps in a test DB in **one line**
- It **composes** — `get_current_user` can itself `Depends(get_session)`; you ask for a user, FastAPI builds the session first, then the user, then tears down in reverse

`Depends` is FastAPI-specific (Django uses middleware, Flask uses `g`, Express uses `app.use`) — but the underlying `yield` mechanism is plain Python.

**Rule of thumb: declare what you need, don't build it.**

---

## L7 — Context managers, and the lifespan

### First principles: why `with` exists at all

Some resources must be released — files, sockets, DB connections. But:

```python
f = open("data.txt")
content = f.read()     # ← if this raises...
f.close()              # ← ...this never runs. Leak.
```

The fix is `try`/`finally` — `finally` runs on **every** exit path, including `return` and exceptions:

```python
f = open("data.txt")
try:
    content = f.read()
finally:
    f.close()          # ironclad
```

Correct but noisy, repeated at every call site, and silently broken the day you forget it. So Python packages it:

```python
with open("data.txt") as f:
    content = f.read()
# closed here, guaranteed
```

**`with` is not magic — it compiles to that `try/finally`.** A *context manager* is just "an object that knows how to set itself up and tear itself down." The "context" is the indented block.

### How an object opts in: `__enter__` / `__exit__`

```python
class Timer:
    def __enter__(self):
        print("[enter]")
        return "value for `as`"          # ← what `as x` receives
    def __exit__(self, exc_type, exc_value, traceback):
        print("[exit]")                  # ← always runs
```

`__exit__`'s three args describe the exception (`None, None, None` on success). Returning `True` from it *swallows* the exception — rarely what you want.

### `@contextmanager`: build one from a generator

The class shape is `setup → block → teardown`. A one-`yield` generator has **exactly that shape**, so:

```python
from contextlib import contextmanager

@contextmanager
def timer():
    print("[enter]")
    try:
        yield "value for `as`"    # ⏸ block runs here
    finally:
        print("[exit]")           # `finally` needed — an exception in the
                                  # block is thrown *into* the generator here
```

**The decorator is the adapter: generator in, context manager out.** It builds the `__enter__`/`__exit__` wrapper for you — `__enter__` runs to the `yield`, `__exit__` resumes it. Without the decorator, `timer()` is just a generator and `with` rejects it (no `__enter__`).

This is where the two earlier lessons join up:

> `yield` pauses a function keeping its locals alive **+** `with` needs setup/teardown
> **=** `@contextmanager`

### Async twins

| Sync | Async |
|---|---|
| `with` | `async with` |
| `__enter__` / `__exit__` | `__aenter__` / `__aexit__` |
| `@contextmanager` | `@asynccontextmanager` |

Needed when setup/teardown itself must `await`.

---

### Lifespan — `init_db()` once at boot

**The problem:** tables must exist before the first query. When do you call `init_db()`?

| Attempt | Why it fails |
|---|---|
| By hand before `uvicorn` | Works, but a human must remember it — one day they won't |
| At module level in `main.py` | **Import now has a side effect.** pytest importing your app writes a real DB file; deploy tools that import to inspect get surprise disk writes; `--reload` re-runs it |
| First request | Every request pays forever for a one-time problem; concurrent cold-start requests race |

All three grope at the same idea: *do this **once**, **after** code loads, **before** the first request.* Import time is too early, request time is too late. That moment has no name in plain Python — so the framework exposes it.

**General rule:** importing a module should *define* things, not *do* things.

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()      # startup
    yield          # ⏸ app serves requests for months
                   # shutdown (nothing needed yet)

app = FastAPI(title=settings.app_name, lifespan=lifespan)
```

**Why a generator and not two `on_startup`/`on_shutdown` functions?** (FastAPI had those; they're deprecated.) Two functions can't share locals, so every resource is forced into a global:

```python
pool = None
def startup():
    global pool          # ← always a smell
    pool = make_pool()
def shutdown():
    pool.close()         # same pool? was startup even called?
```

With `yield`, the frame stays alive, so `pool` is an ordinary local that the teardown *provably* shares with the setup. Setup and teardown become one function with a gap — they can't drift apart.

Same shape at two timescales:

```python
def get_session():        # per request
    with SessionLocal() as s:
        yield s
async def lifespan(app):  # per process
    init_db()
    yield
```

Details: `async` because startup runs on the event loop (nothing to do with speed). The `app` param is handed to you so you can stash things on it. **`lifespan=lifespan` — no parentheses**, same rule as `Depends`.

### ⚠ Defining ≠ wiring
Writing `lifespan` but forgetting `lifespan=lifespan` gives you a **perfectly working server that silently never creates the tables**. Python has no idea a function named `lifespan` was meant to be one — frameworks only run what you explicitly hand them. Loud bugs (`NameError`) are cheap; silent ones cost an afternoon.

### ⚠ Teardown isn't unconditional
Code after `yield` runs only if the interpreter survives to run it. Ctrl+C / `SIGTERM` → graceful unwind, cleanup runs. `SIGKILL` / power cut / OOM → the frame vanishes and nothing after `yield` ever happens. (This is why databases have crash recovery — clients can't be trusted to close politely.)

### ✅ Verified live
```
INFO:  Waiting for application startup.      ← entering the context manager
       PRAGMA main.table_info("users")       ← init_db() running
INFO:  Application startup complete.         ← hit the yield, paused
GET /health 200 OK
```
The SQL lands between those two log lines because that's exactly where `init_db()` sits in the function. No `CREATE TABLE` — just the `PRAGMA` existence check, since the table was already there. **Idempotency caught in the act.**

`/openapi.json` reported `"title": "Ctrl+Teach API (dev)"` — the `(dev)` proves `.env` → `settings` → live app.

### 🔜 Next up
The endpoint. Nothing touches the DB *during a request* yet. Then: `/users/999` returns **500** (`AttributeError` on `None`) because `session.get` returns `None` for a missing row → `HTTPException(404)`.
