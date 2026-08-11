#!/usr/bin/env bash
# The ADP instance duva-bench studies record into — deliberately not the one
# anyone develops ADP against.
#
# On 2026-08-10 a gate G2 re-run reached 7 of 8 recorded trials twice and lost
# them both times, because another workstream ran `make up` in ~/dev/adp and
# replaced the database mid-study. The failure arrives as a connection reset,
# then a 401 from a token whose database no longer exists, then a 404 for a
# repository that was created minutes earlier — and none of that names the cause.
#
# Three decisions make this stack survivable, and each is here because its
# absence cost a run:
#
#   1. **Its own worktree** (~/dev/adp-duvabench, pinned to a commit). Branch
#      switches and merges in the main checkout cannot reach it.
#   2. **A project name outside `adp-test-*`.** ADP's `make down-all` sweeps
#      every `adp-test-*` stack on the machine; `duvabench-adp` is not one.
#   3. **The built server, never `npm run dev`.** `dev` is `tsx watch`, ADP's
#      GIT_ROOT sits inside its own checkout, and duva-bench publishes a commit
#      per trial — so the watcher restarts the server under a running study.
#
# It also listens on 3100 rather than 3000, so a dev instance and this one can
# both exist without either noticing.
#
# Usage:
#   tools/adp-stack.sh up       # create/refresh and start; prints nothing secret
#   tools/adp-stack.sh start    # start an existing stack's server
#   tools/adp-stack.sh status   # is it up, and at what contract version
#   tools/adp-stack.sh creds    # write the env file this repo's tools source
#   tools/adp-stack.sh down     # stop the server and tear the stack down
set -euo pipefail

ADP_SOURCE="${ADP_SOURCE:-$HOME/dev/adp}"
WORKTREE="${DUVA_ADP_WORKTREE:-$HOME/dev/adp-duvabench}"
PROJECT="${DUVA_ADP_PROJECT:-duvabench-adp}"
PORT="${DUVA_ADP_PORT:-3100}"
BASE_URL="http://localhost:${PORT}"
# Credentials go outside the repository, and the caller decides where. Tokens
# are never written into the tree (execution-plan §0.7).
CREDS="${DUVA_ADP_CREDS:-${TMPDIR:-/tmp}/duva-adp.env}"
PIDFILE="$WORKTREE/.adp-duvabench.pid"
LOGFILE="$WORKTREE/.adp-duvabench.log"

say() { printf '%s\n' "$*" >&2; }

ensure_worktree() {
	if [ -d "$WORKTREE" ]; then return; fi
	say "creating $WORKTREE from $ADP_SOURCE (origin/main)"
	git -C "$ADP_SOURCE" fetch --quiet origin
	git -C "$ADP_SOURCE" worktree add "$WORKTREE" origin/main --detach
	npm ci --prefix "$WORKTREE/server"
}

start_server() {
	if curl -fsS -m 2 "$BASE_URL/healthz" >/dev/null 2>&1; then
		say "already listening on $PORT"
		return
	fi
	# shellcheck disable=SC1091
	set -a
	. "$WORKTREE/.env.test"
	set +a
	export PORT PUBLIC_URL="$BASE_URL"
	( cd "$WORKTREE/server" && setsid nohup npm start >"$LOGFILE" 2>&1 </dev/null & echo $! >"$PIDFILE" )
	local waited=0
	until curl -fsS -m 2 "$BASE_URL/healthz" >/dev/null 2>&1; do
		sleep 2
		waited=$((waited + 2))
		if [ "$waited" -gt 120 ]; then
			say "server did not come up in ${waited}s; see $LOGFILE"
			exit 1
		fi
	done
	say "listening on $PORT"
}

case "${1:-status}" in
up)
	ensure_worktree
	# `make up` alone leaves an unmigrated database, and `bootstrap.ts` then
	# fails with a bare Postgres parserOpenTable error that names nothing.
	( cd "$WORKTREE" && ADP_TEST_PROJECT="$PROJECT" make up )
	# shellcheck disable=SC1091
	( cd "$WORKTREE" && set -a && . .env.test && set +a \
		&& npm run migrate --prefix server && npm run build --prefix server )
	start_server
	;;
start)
	start_server
	;;
status)
	if curl -fsS -m 2 "$BASE_URL/healthz" >/dev/null 2>&1; then
		version=$(curl -fsS -i -m 3 "$BASE_URL/version" | awk -F': ' 'tolower($1)=="adp-api-version"{print $2}' | tr -d '\r')
		say "up on $PORT, contract ${version:-unknown}, project $PROJECT"
	else
		say "down (project $PROJECT, port $PORT)"
		exit 1
	fi
	;;
creds)
	# shellcheck disable=SC1091
	set -a
	. "$WORKTREE/.env.test"
	set +a
	runner=$(cd "$WORKTREE/server" && npx tsx src/bootstrap.ts "duva-runner-$$" 2>/dev/null | awk '/^Token:/{print $2}')
	grader=$(cd "$WORKTREE/server" && npx tsx src/bootstrap.ts "duva-grader-$$" 2>/dev/null | awk '/^Token:/{print $2}')
	if [ -z "$runner" ] || [ "$runner" = "$grader" ]; then
		say "could not mint two distinct principals; is the stack up and migrated?"
		exit 1
	fi
	umask 077
	{
		echo "# duva-bench's dedicated ADP. Regenerate with tools/adp-stack.sh creds."
		echo "export DUVA_ADP_BASE_URL=$BASE_URL"
		echo "export DUVA_ADP_RUNNER_TOKEN=$runner"
		echo "export DUVA_ADP_GRADER_TOKEN=$grader"
		echo "export DUVA_ADP_OWNER=duva"
		echo "export DUVA_ADP_REPO=bench-smoke"
		echo "export DUVA_ADP_DB_URL=$DATABASE_URL"
	} >"$CREDS"
	curl -fsS -X POST "$BASE_URL/api/v3/repos/duva" \
		-H "Authorization: Bearer $runner" -H "Content-Type: application/json" \
		-d '{"name":"bench-smoke"}' >/dev/null 2>&1 || true
	say "wrote $CREDS (two principals, repo duva/bench-smoke)"
	;;
down)
	[ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null || true
	rm -f "$PIDFILE"
	( cd "$WORKTREE" && ADP_TEST_PROJECT="$PROJECT" make down ) || true
	say "stack $PROJECT is down"
	;;
*)
	say "usage: $0 [up|start|status|creds|down]"
	exit 2
	;;
esac
