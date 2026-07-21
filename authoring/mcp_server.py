"""MCP transport for the authoring tools (mcp-authoring capability).

A streamable-HTTP MCP endpoint, authenticated by an `McpCredential`
bearer token that binds the whole session to exactly one creator user.
Every tool runs as that creator through `authoring.tools.AuthoringTools`.

The module is import-guarded: if the `mcp` SDK is unavailable the ASGI
factory returns a tiny "unavailable" app instead of raising, so
`geogame.asgi` (imported across the test suite) can never break.
"""
import contextvars
import json

from asgiref.sync import sync_to_async

_current_tools = contextvars.ContextVar('authoring_tools', default=None)

try:
    from mcp.server.fastmcp import FastMCP
    _MCP_AVAILABLE = True
except Exception:  # noqa: BLE001 - SDK optional at import time
    FastMCP = None
    _MCP_AVAILABLE = False


def _tools():
    tools = _current_tools.get()
    if tools is None:
        raise RuntimeError('No authenticated authoring session on this request.')
    return tools


def _build_server():
    """Construct the FastMCP server with every read + stage tool."""
    server = FastMCP(
        name='cercetador-authoring',
        instructions=(
            'Author scouting geo-game content. Read the available '
            'collections, geometry, challenges, games, roles, and the '
            'config schema; then STAGE proposals (never live writes). A '
            'human approves and applies them. Every challenge suggestion '
            'needs a rationale.'
        ),
        stateless_http=True,
    )

    def register(name, method_name, is_async_payload=False):
        async def _tool(**kwargs):
            method = getattr(_tools(), method_name)
            result = await sync_to_async(method)(**kwargs)
            return json.dumps(result, default=str)
        _tool.__name__ = name
        server.tool(name=name)(_tool)

    # Read / discovery
    register('list_collections', 'list_collections')
    register('get_collection', 'get_collection')
    register('list_towers', 'list_towers')
    register('list_zones', 'list_zones')
    register('list_challenges', 'list_challenges')
    register('list_games', 'list_games')
    register('get_game', 'get_game')
    register('list_team_groups', 'list_team_groups')
    register('list_game_roles', 'list_game_roles')
    register('describe_config_schema', 'describe_config_schema')
    # Proposal management
    register('open_proposal', 'open_proposal')
    register('get_proposal', 'get_proposal')
    register('list_my_proposals', 'list_my_proposals')
    register('submit_for_approval', 'submit_for_approval')
    register('withdraw_proposal', 'withdraw_proposal')
    # Suggest / stage writes
    register('propose_collection', 'propose_collection')
    register('propose_tower', 'propose_tower')
    register('propose_zone', 'propose_zone')
    register('propose_game', 'propose_game')
    register('propose_game_role', 'propose_game_role')
    register('propose_config', 'propose_config')
    register('propose_link', 'propose_link')
    register('suggest_challenge', 'suggest_challenge')
    return server


_server = None
_inner_app = None


def _server_app():
    global _server, _inner_app
    if _server is None:
        _server = _build_server()
        _inner_app = _server.streamable_http_app()
    return _inner_app


def _bearer_token(scope):
    for key, value in scope.get('headers', []):
        if key == b'authorization':
            raw = value.decode('latin-1')
            if raw.lower().startswith('bearer '):
                return raw[7:].strip()
    return None


async def _reject(send, status_code, message):
    body = json.dumps({'error': message}).encode('utf-8')
    await send({
        'type': 'http.response.start',
        'status': status_code,
        'headers': [(b'content-type', b'application/json')],
    })
    await send({'type': 'http.response.body', 'body': body})


@sync_to_async
def _authenticate(token, scope_headers):
    """Resolve the credential → creator and open an AuthoringSession."""
    from .models import AuthoringSession, McpCredential
    from .tools import AuthoringTools

    credential = McpCredential.verify(token)
    if credential is None:
        return None
    client_name = ''
    llm_model = ''
    for key, value in scope_headers:
        if key == b'x-mcp-client':
            client_name = value.decode('latin-1')[:120]
        elif key == b'x-mcp-model':
            llm_model = value.decode('latin-1')[:120]
    session = AuthoringSession.objects.create(
        created_by=credential.created_by,
        credential=credential,
        client_name=client_name,
        llm_model=llm_model,
    )
    return AuthoringTools(credential.created_by, session=session)


def authoring_asgi_app():
    """ASGI app: authenticate the bearer token, then serve the MCP app.

    Safe to call even when the SDK is missing — returns a small app that
    reports 503 rather than raising at import/mount time.
    """
    if not _MCP_AVAILABLE:
        async def _unavailable(scope, receive, send):
            if scope['type'] != 'http':
                return
            await _reject(send, 503, 'MCP authoring server is unavailable.')
        return _unavailable

    async def _app(scope, receive, send):
        if scope['type'] != 'http':
            return
        token = _bearer_token(scope)
        if not token:
            await _reject(send, 401, 'Missing MCP bearer credential.')
            return
        tools = await _authenticate(token, scope.get('headers', []))
        if tools is None:
            await _reject(send, 401, 'Invalid or revoked MCP credential.')
            return
        reset = _current_tools.set(tools)
        try:
            await _server_app()(scope, receive, send)
        finally:
            _current_tools.reset(reset)

    return _app
