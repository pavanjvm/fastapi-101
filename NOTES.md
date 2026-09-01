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

---

## L8 — The endpoint (path params + `Depends`)

```python
@app.get("/users/{user_id}")
def read_user(user_id: int, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    return {"id": user.id, "name": user.name}
```

### Problem 1: the URL carries data
`/users/1` and `/users/7` are the same operation with a different input — so part of the URL is an **argument**, not an address. `{user_id}` marks the hole, and **the name in the braces must match the parameter name** — that's the whole binding mechanism.

### Problem 2: everything off the wire is a string
HTTP has no types. `"1"` arrives as bytes; `/users/abc` is equally valid HTTP. Without the framework, every endpoint opens with the same boilerplate:

```python
try:
    user_id = int(user_id)
except ValueError:
    return JSONResponse({"detail": "..."}, status_code=422)
```

FastAPI's move: **you already write the type down anyway.** `user_id: int` generates the conversion *and* the 422. Same trick as `Mapped[int]` — **declare the shape, get the enforcement free.** That's the core idea of the entire framework.

### Problem 3: why not one global Session?
```python
session = SessionLocal()   # module level — badly broken
```
Three failures, each following from what a Session *is*:

| A Session is... | ...so sharing it means |
|---|---|
| one **transaction** | Bob sees Alice's uncommitted rows; her rollback reverts his work |
| an **identity map** (caches loaded rows) | nothing ever refreshes — permanent stale reads |
| **not thread-safe** | sync `def` handlers run in a threadpool → concurrent mutation, intermittent corruption under load |

Forced conclusion: **one session per request**, shared with nobody.

### Problem 4: so who builds it?
Doing it inline is *correct*:
```python
with SessionLocal() as session:      # fine! but...
```
…it gets copy-pasted into all 40 endpoints, hard-wires each one to `SessionLocal` (so testing needs monkey-patching), and once auth/permissions/rate-limits each bring their own `with`, endpoints become nested boilerplate with two real lines at the bottom.

The insight: **setup/teardown isn't the endpoint's job.** It doesn't want to *build* a session, it wants to *be given* one. The framework is already wrapping the call — let it. And you already have a place listing what a function needs: **the parameter list.**

```python
session: Session = Depends(get_session)   # "don't expect a caller to pass this — run this and give me what it yields"
```

**No parentheses.** `Depends(get_session())` would call it once at import → the global-session bug with extra steps.

### The two params are unrelated
| Parameter | Source |
|---|---|
| `user_id: int` | the **URL** (name matches `{user_id}`) |
| `session: Session` | the **`Depends`** — nothing to do with the URL |

FastAPI reads the signature **once at startup** and builds a plan; nothing is guessed per request:
```
"1" → int → 1                 (or 422, and you're never called)
g = get_session() → next(g)   session opens ⏸
    read_user(1, session)     ← the only line you wrote
                 next(g)      session closes
```

### ✅ Verified live
| Request | Result |
|---|---|
| `/users/1` | **200** `{"id":1,"name":"changed"}` |
| `/users/abc` | **422** `{"loc":["path","user_id"],"msg":"Input should be a valid integer","input":"abc"}` — precise, machine-readable, free |
| `/users/999` | **500** `AttributeError: 'NoneType' object has no attribute 'id'` |

The SQL emitted:
```sql
SELECT users.id, users.name FROM users WHERE users.id = ?
```
**`= ?`** — the value is sent separately, never parsed as SQL. A `user_id` of `1; DROP TABLE users` is only ever *compared*, never executed. SQL injection is **structurally** impossible, not just unlikely.

On the 999 case: the query ran fine and returned zero rows. **The DB was happy** — the failure was purely Python assuming a row came back.

### 🔜 Next up
L9 — turning that 500 into a 404 with `HTTPException`.

---

## L9 — From a crash to an API (`HTTPException`)

```python
from fastapi import Depends, FastAPI, HTTPException

@app.get("/users/{user_id}")
def read_user(user_id: int, session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return {"id": user.id, "name": user.name}
```

### What actually happened
`session.get` returns **`None`** for a missing row — not an error, not an empty object. Then `.id` on `None` raises `AttributeError`, nothing catches it, FastAPI's top-level net converts it to 500.

Why doesn't FastAPI handle it? Because **`None` is only meaningful to you.** The framework sees a function that raised; it can't know whether that meant "row missing" or "database on fire."

### Why 500 is a lie
Status codes are a **contract**, and the first digit is the whole message:

| | Meaning | Whose fault |
|---|---|---|
| 2xx | worked | — |
| 4xx | bad request | **client's** |
| 5xx | I broke | **server's** |

`/users/999` is a well-formed request for a row that doesn't exist → **404**. Machines act on that digit:

- **Monitoring pages someone** — 5xx rate is the classic alert. A URL typo wakes someone at 3am.
- **Clients retry** on 5xx ("transient, try again"). It'll fail identically forever. 404 means "settled, don't bother."
- **The frontend can't respond properly** — "user not found" vs "try again later." Only one is true.
- An unhandled 500 in debug mode can **leak the stack trace** — paths, versions, SQL — to whoever asked.

> **A crash and an error are different things.** A crash is unplanned; an error is a documented outcome you designed. Converting the first into the second is most of what "production-ready" means.

### ⚠ The wrong fix
```python
return {"error": "user not found"}      # ← this is 200 OK
```
You've said *"success, here's your user"* and attached an error message. Every client checks the status, sails past, and crashes later on a missing field far from the cause. **Never signal failure in the body while the status says success.**

### Why `raise`, not `return`
`return JSONResponse(..., status_code=404)` works fine for a 2-line endpoint. But `return` exits **one function**, and real code has depth:

```
read_user() → get_user_with_permissions() → load_user()   ← discovers it's missing HERE
```

Every intermediate layer would need error-checking code for a problem it has nothing to do with, and one missed check lets the `None` travel until it crashes somewhere unrelated (**exactly what happened in L8**).

An exception is a **non-local exit** — it unwinds the stack until something catches it. FastAPI puts a catcher at the top listening for `HTTPException`. So: *abort with this status, from any depth, no intermediate cooperation required.*

### Details worth keeping
- **`is None`, not `if not user`** — `not user` is also true for `""`, `0`, `[]`. Test for what you actually mean; it'll bite the day the value is legitimately `0`.
- **Guard clause first**, happy path unindented below. Beats an `else` once there are four checks and you'd be four levels deep.
- **422 you never wrote** (generated from `user_id: int`); **404 you had to write** — only you know what a missing row means. That's the line between what a framework can infer and what it can't.

### ⚠ Bugs in error handlers hide
Forgetting to import `HTTPException` gives a `NameError` — but only inside the `if`, so the app boots, `/users/1` works, and the failure appears *only* when a user is missing → **a 500 again**, from a totally different cause. **Error-path bugs only fire on the error path, which is the path nobody exercises.**

### ✅ Verified live
| Request | Status | Body |
|---|---|---|
| `/users/1` | **200** | `{"id":1,"name":"changed"}` |
| `/users/999` | **404** | `{"detail":"user not found"}` |
| `/users/abc` | **422** | validation detail |
| `/health` | **200** | `{"status":"ok"}` |

**Zero tracebacks in the log** — the real signal. Before, a missing user printed a full stack trace ("nobody anticipated this"). Now the log stays quiet, because nothing went wrong.

### 🔜 Next up
`response_model`. `return {"id": ..., "name": ...}` hides a flaw that's invisible with two columns and becomes a security problem the moment `User` grows a `password_hash`.

---

## L10 — Output contracts with `response_model`

Returning a hand-built dictionary is safe but fragile:

```python
return {"id": user.id, "name": user.name}
```

Every endpoint author must remember every sensitive field forever. The tempting shortcut is worse:

```python
return user
```

FastAPI then serializes the whole ORM object. After adding and seeding a non-empty `password_hash`, the actual 85-byte response was:

```json
{"password_hash":"L10_SUPER_SECRET_HASH_DO_NOT_EXPOSE","id":3,"name":"L10 Leak Demo"}
```

The fix is one reusable, explicit output allow-list:

```python
from pydantic import BaseModel

class UserOut(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}
```

`from_attributes=True` lets Pydantic obtain those fields from `user.id` and `user.name` instead of requiring a dictionary. It does **not** activate the protection; the route must enforce the model:

```python
@app.get("/users/{user_id}", response_model=UserOut)
def read_user(...):
    ...
    return user
```

`response_model` now sits between the returned object and the network: validate the declared fields, discard everything else, then serialize.

### ✅ Verified live

The same database query still selected `users.password_hash`, so the ORM object still contained the secret. But the protected HTTP body was only 31 bytes:

```json
{"id":3,"name":"L10 Leak Demo"}
```

The secret disappeared because `UserOut` did not permit it—not because the endpoint author manually remembered to remove it.

### 🔜 Next up
Flesh out `User`, then add its one-to-one `Profile` model.

---

## L11 — Modeling a real `User`

A database model records invariants, not just fields. The completed user separates:

- required identity/auth data: `id`, unique indexed `username`, `password_hash`
- optional account data: `email`, `name`, `picture`, `timezone`, `last_login`
- server-owned data: `is_admin=False` and a per-row UTC `created_at`

`NULL` means “no value”; it is different from the present-but-empty string `""`. SQLAlchemy derives the same rule from the Python type: `Mapped[str]` is not nullable, while `Mapped[str | None]` is nullable.

Defaults and nullability answer separate questions: a default supplies an omitted value; `nullable` controls whether the stored value may be absent. `password_hash` therefore has no empty default—forgetting it must fail instead of creating a broken account.

Timestamp defaults receive a callable:

```python
default=lambda: datetime.now(timezone.utc)
```

Using `default=datetime.now(...)` would calculate one timestamp at import time and reuse that stale value.

### ✅ Verified live

Fresh `CREATE TABLE` SQL contained `NOT NULL` only for required fields and created `CREATE UNIQUE INDEX ix_users_username`. Inserting `pavan` generated `is_admin=False`, a current UTC `created_at`, and `NULL` optional values. A second `pavan` insert rolled back with:

```text
IntegrityError: UNIQUE constraint failed: users.username
```

### 🔜 Next up
L12 — model a one-to-one `Profile` and enforce that every user can have at most one.

---

## L12 — One user, one `Profile`

`User` holds account/authentication data; `Profile` holds optional learning data such as bio, grade, school, languages, and preferences. The tables connect through a shared key:

```text
profiles.user_id ──→ users.id
```

Two database rules give that arrow its meaning:

```python
user_id: Mapped[int] = mapped_column(
    ForeignKey("users.id"),  # the referenced user must exist
    primary_key=True,        # a user_id may appear only once here
)
```

A foreign key alone would allow several profiles to point at one user. Making `user_id` the profile's primary key enforces at most one profile per user and removes the need for a separate profile ID.

Lists and dictionaries are stored as JSON. Their defaults are factories:

```python
languages: Mapped[list[str]] = mapped_column(JSON, default=list)
preferences: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
```

`default=list` hands SQLAlchemy the list-making function, so each profile receives a fresh `[]`; `default=[]` would hand it one already-created mutable object.

### SQLite foreign-key trap

The first live test found `PRAGMA foreign_keys = 0`: SQLite recorded the foreign key in `CREATE TABLE` but did not enforce it. Because the setting belongs to each connection, the engine now runs this whenever it opens one:

```python
@event.listens_for(engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
```

### ✅ Verified live

```text
PRAGMA foreign_keys = 1
orphan user_id=999       → IntegrityError: FOREIGN KEY constraint failed
second profile for user 1 → IntegrityError: UNIQUE constraint failed: profiles.user_id
profile 1 languages      → []
profile 2 languages      → []
same languages box       → False
```

### 🔜 Next up
L13 — password hashing: why plaintext and reversible encryption both fail.

---

## L13 — Password hashing with Argon2

Plaintext storage exposes every password as soon as the database leaks. Reversible encryption still requires the server to hold a decryption key, so stealing the database and key reveals the originals. Login only needs to answer “does this password match?”, so passwords use a one-way hash.

An ordinary fast hash is unsuitable because attackers can test guesses extremely quickly. A password hasher is deliberately expensive. It also adds a different random salt for every hash, preventing identical passwords from producing identical stored strings and defeating reusable precomputed tables.

The new backend uses the current FastAPI-recommended stack:

```text
pwdlib  → Python password-hashing interface
Argon2  → slow, memory-intensive hashing algorithm
```

Installed with:

```bash
uv add "pwdlib[argon2]"
```

`app/security.py` owns the policy behind one application-level doorway:

```python
from pwdlib import PasswordHash

password_hasher = PasswordHash.recommended()

def hash_password(password: str) -> str:
    return password_hasher.hash(password)
```

### ✅ Verified live

Hashing the same password twice produced two different `$argon2id$...` strings because each received a fresh salt:

```text
hashes equal:     False
correct password: True
wrong password:   False
```

The password hash stays in the database and is never sent to the client. JWTs solve a later, different problem: proving that a login already succeeded.

---

## L14 — `/register`

### The problem
Turn untrusted JSON into a row, without the plaintext password ever reaching the database.

### Two schemas, not one
`UserOut` is the outgoing shape. Registration needs an incoming one — and it carries a
plaintext password that must never appear in a response.

```python
class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=8, max_length=128)
```

Bare `str` only means "it's text" — `{"username": "", "password": ""}` would pass. The
low-level fix is `if len(...) < 8: raise HTTPException(...)` inside the route, but then the
rule lives in the route, repeats for every route, and never shows up in the OpenAPI docs.

`Field()` attaches the constraint to the annotation itself, so Pydantic builds it into the
validator and FastAPI returns 422 **before the function body runs**.

`max_length` on a password is not cosmetic: Argon2's cost scales with input size, so an
uncapped field lets someone POST 10 MB and burn CPU.

### Gotcha — unknown kwargs fail silently
`Field(min_lenght=3)` does not raise. Pydantic v2 treats an unrecognised keyword as extra
JSON-schema metadata, so the constraint is simply never enforced.

### The route

```python
@app.post("/register", response_model=UserOut, status_code=201)
def register(payload: UserCreate, session: Session = Depends(get_session)):
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
    )
    session.add(user)
    session.commit()
    return user
```

- A Pydantic model as a parameter → FastAPI reads it from the **body**. A scalar matching a
  path placeholder (`user_id: int`) → read from the **path**.
- `201` means "I created something"; `200` means "here's what you asked for".
- `hash_password` runs before `session.add`, so the plaintext only ever exists as a local
  variable and cannot accidentally be persisted.

### Gotcha — `=` vs `:`
`payload = UserCreate` is a *default value* (the class object itself), not an annotation.
FastAPI then sees an untyped parameter and never reads the body at all.

---

## L15 — Migrations (Alembic)

### The problem, concretely
`ctrlteach.db` on disk said `users: id, name`. `app/db.py` said `users: id, username,
password_hash, ...`. They disagreed, so any INSERT would hit "no such column".

`create_all()` cannot fix this. It creates **missing tables** and never alters an existing
one. It is not a migration system.

### Deriving the tool
Fixing it by hand is one line:

```sql
ALTER TABLE users ADD COLUMN password_hash VARCHAR(255);
```

That works — on *one* database. But there's also a teammate's, staging, and production.
So write the change to a committed file instead, and `git pull` carries it to everyone.

**That file is a migration.** Nothing more.

The only hard part: how does a given database know which files it already ran? It
remembers, in one extra table:

```text
alembic_version:  abc123
```

So `alembic upgrade head` = read the bookmark, find the newest revision, run everything
between in order, update the bookmark.

### ORM vs migrator
SQLAlchemy maps objects to rows **at runtime** and assumes the table already has the right
shape. Alembic changes that shape **at deploy time**. Drizzle bundles both halves
(`drizzle-orm` + `drizzle-kit`); same split, one brand name.

| Drizzle | SQLAlchemy |
|---|---|
| `drizzle-kit generate` | `alembic revision --autogenerate` |
| `drizzle-kit migrate` | `alembic upgrade head` |
| `meta/_journal.json` | `alembic_version` table |

The migrator needs the schema's **history**, not just its current state — a different kind
of state, which is why it lives in the DB rather than in the code.

### Setup

```bash
uv add alembic
uv run alembic init alembic
```

`alembic/env.py` ships as a file *you own*, because Alembic can't guess two things:

```python
from app.config import settings
from app.db import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)
...
target_metadata = Base.metadata
```

- **Where the models are.** Autogenerate diffs `Base.metadata` against the live DB; the stub
  ships `target_metadata = None`, so every diff comes out empty. Importing `app.db` also
  *executes* it, which is what runs `class User(Base)` and registers the table. **A model in
  a file nothing imports is invisible to autogenerate** — and may get dropped by it.
- **Which database.** `sqlalchemy.url` in `alembic.ini` is blanked deliberately: the URL
  belongs in `.env` via `app/config.py`. Two sources of truth drift, and `alembic.ini` is
  committed, so a prod URL with a password would land in Git.

`poolclass=pool.NullPool` in the stub: a migration opens one connection and exits. A pool
exists to reuse connections across many requests; a one-shot script has no use for one.

### Backfilling existing rows
Autogenerate knows the shape you want, never what old rows should contain. Three cases:

1. **A sensible default exists** — `server_default="UTC"`, and the database fills every row
   during the ALTER. Note `default=` in `db.py` is *Python-side*: SQLAlchemy applies it when
   you construct an object, so it does nothing for rows that already exist.
2. **Value must be computed** — add nullable → `op.execute("UPDATE ...")` → `alter_column`
   to `NOT NULL`. This is why migrations are Python, not plain SQL. On a large table the
   UPDATE gets batched rather than run as one table-locking transaction.
3. **No right answer** — leave it nullable. `NULL` honestly means "unknown"; inventing a
   value to satisfy a constraint fills the DB with `""` and `1970-01-01`.

### Deploys are not atomic — expand then contract

```text
deploy 1:  add column (nullable)     old code ignores it
deploy 2:  ship code that writes it; backfill old rows
deploy 3:  NOT NULL; drop old column
```

Each step is safe with either version of the code live. Dropping is the dangerous
direction: the moment the column is gone, any still-running old instance that selects it
throws.

### Rules
- A schema change and its migration go in **the same commit**. Model without migration =
  every teammate's `upgrade head` is a no-op and their app crashes on a stale table.
- Migrations are **append-only once pushed**. Editing an applied revision leaves other DBs
  claiming a version they don't actually have.
- Renames autogenerate as **drop + add** — harmless on an empty column, data loss on a
  teammate's DB. Always read the generated file before running it.
- `init_db()` / `create_all()` must come out of the lifespan once Alembic owns the schema.
  On a fresh DB `create_all()` builds the tables without stamping a version, and Alembic
  then tries to create them again and fails.

### ⏸ Where this paused
`env.py` and `alembic.ini` are wired. Still to run:

```bash
Remove-Item ctrlteach.db          # last time; history starts at zero
uv run alembic revision --autogenerate -m "create users and profiles"
uv run alembic upgrade head
```

Deleting rather than migrating on top is a *learning-repo* shortcut: the stale table holds
one junk row, and `password_hash NOT NULL` can't be added to it without the nullable →
backfill → tighten dance (SQLite won't add a NOT NULL column without a DEFAULT at all).

---

## L15b — Finishing the migration, and the two `/register` bugs

### Ran it

```bash
Remove-Item ctrlteach.db
uv run alembic revision --autogenerate -m "create users and profiles"   # 320b5dbacda3
uv run alembic upgrade head
```

`alembic_version` now holds exactly one row. `users` has all ten columns, `profiles` exists.

### `init_db()` had to go — the concrete failure

Not a style rule. With it still wired, on a fresh DB:

1. app boots → `create_all()` creates `users`
2. `alembic upgrade head` reads `alembic_version`, finds it empty, concludes nothing has run
3. runs the first migration → `CREATE TABLE users` → **`table users already exists`**

`create_all()` writes no version row, so Alembic has no way to learn the tables are already
there. One owner of the schema, and it's Alembic now. Removed the call, the import, the
function — and the `lifespan` wrapper with it, since that was all it contained.

`lifespan` isn't obsolete; it's still the hook for a Redis pool or a model load. Schema
creation just wasn't a legitimate use of it.

### Bug 1 — a 500 *after* a successful insert

```python
class UserOut(BaseModel):
    name: str          # required
```

`/register` never sets `name`, and `User.name` is nullable — so `user.name` is `None`.
`response_model=UserOut` converts the returned object *after* `commit()` has already
written the row. Pydantic sees `None` where it demanded a `str` and raises, nothing catches
it → **500, with the user sitting in the database.**

The fix is to make the schema agree with the model:

```python
class UserOut(BaseModel):
    id: int
    username: str          # non-null in the DB, and the field that actually identifies a user
    name: str | None = None
    model_config = {"from_attributes": True}
```

`username` was a separate improvement — the old response was `{"id": 1, "name": null}`,
which tells the caller nothing. It doesn't replace the `name` fix; without both, it still
500s.

### Bug 2 — duplicate username

```python
session.add(user)
try:
    session.commit()
except IntegrityError:
    session.rollback()
    raise HTTPException(status_code=409, detail="username taken")
return user
```

**Why not a pre-check `SELECT`?** It's a race. Two requests can both run the SELECT, both
see nothing, and both proceed. The `UNIQUE` constraint is the only check that can't be
raced, because the database applies it at write time. Let it be the judge and handle the
error it throws.

`rollback()` is mandatory — after an `IntegrityError` the session is in a failed transaction
and every later statement on it errors until it's reset.

409 Conflict, not 400: the request was well-formed, it just collides with existing state.

### ✅ Verified live

```text
POST /register {"username":"checkuser","password":"hunter22"}
  → 201  {"id":1,"username":"checkuser","name":null}
  → 409  {"detail":"username taken"}
```

### ⚠ Gotcha
Deleting the `lifespan` function but leaving `lifespan=lifespan` in the `FastAPI(...)` call
is a `NameError` at import — the app won't start at all. The mirror image of L7's silent
failure: forgetting to *wire* a lifespan is quiet, forgetting to *unwire* one is loud.

### 🔜 Next up
Login: verifying a password and issuing a JWT.
