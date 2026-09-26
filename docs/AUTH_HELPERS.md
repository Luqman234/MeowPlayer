# Account authentication helpers

MeowPlayer keeps provider authentication outside the player process.

The current implementation ships one helper:

```text
meowplayer-google-auth
```

There is no Xiaomi / Mi Account helper.

## Why this boundary exists

Account Nest needs account-specific data, but the music player should not become
responsible for every provider's browser flow, refresh-token rules, credential
store, or future authentication changes.

The boundary is:

```text
MeowPlayer
    ↓
external helper command
    ↓
provider authentication
```

The Google account adapter still owns YouTube Data API parsing. It gets the
credential by invoking the helper.

## Command contract

A helper command receives one action as its final argument.

### `status`

```text
helper status
```

Exit codes:

- `0`: a reusable/refreshable account session is available.
- `1`: disconnected.
- any other code: helper/configuration failure.

Human-readable stdout is allowed for this action.

### `login`

```text
helper login
```

Perform interactive authorization and persist whatever provider state the
helper needs.

Exit `0` only after the account is usable.

Do not print access tokens to stdout.

### `token`

```text
helper token
```

Return one currently usable access token.

Requirements:

- exit `0` on success;
- stdout contains the token and nothing else except a trailing newline;
- refresh an expired access token before returning when possible;
- diagnostics go to stderr;
- never log the token.

This is the machine-readable operation consumed by MeowPlayer.

### `logout`

```text
helper logout
```

Disconnect according to provider policy. A helper should remove local
credential state and should revoke remotely when the provider exposes an
appropriate supported revocation mechanism.

Exit `0` when local disconnection has completed.

## Selecting a helper

The Google Account Nest defaults to:

```text
meowplayer-google-auth
```

Override it with:

```bash
meowplayer --google-account --google-auth-command '/path/to/helper'
```

or:

```bash
export MEOWPLAYER_GOOGLE_AUTH_COMMAND='/path/to/helper'
```

Commands may include fixed arguments; MeowPlayer parses the command with
`shlex.split()` and appends the action without invoking a shell.

## Packaged Google helper

`google_auth_helper.py` implements:

- system-browser Google authorization;
- PKCE S256;
- random OAuth state;
- loopback callback on `127.0.0.1`;
- read-only YouTube authorization;
- local OAuth state storage;
- access-token refresh;
- logout/revocation.

The first login needs a Google Desktop OAuth client ID:

```bash
export MEOWPLAYER_GOOGLE_CLIENT_ID='YOUR_CLIENT_ID.apps.googleusercontent.com'
meowplayer-google-auth login
```

The saved token state includes the public client ID, so later helper
invocations can reuse it.

## Credential ownership

The player core must not:

- read a helper's refresh-token database;
- implement a provider password form;
- copy refresh tokens into MeowPlayer state;
- log access tokens;
- assume how a helper stores credentials;
- assume that another provider uses Google's OAuth model.

The helper owns its provider credentials.

MeowPlayer receives only the short-lived credential required for the immediate
provider API request.

## Future providers

A future provider should get its own supported authentication helper or adapter
rather than extending the Google helper with unrelated private protocols.

In particular, **Mi Account / Xiaomi authentication is not implemented**.

Do not use Xiaomi Passport passTokens, Mi Unlock client identifiers, embedded
unlock signing material, or other applications' credentials as a shortcut for
a future Xiaomi integration.
