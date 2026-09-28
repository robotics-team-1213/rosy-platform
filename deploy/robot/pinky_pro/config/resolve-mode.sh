# Canonical runtime mode from board.yaml. Source this file; do not execute it.
# Overlay YAML exists only for catalog modes. Aliases never get their own copy.

resolve_runtime_mode() {
    local requested="${1:-}"
    local board="${2:-}"
    if [[ -z "$requested" || -z "$board" ]]; then
        echo "error: resolve_runtime_mode requires mode and board.yaml" >&2
        return 2
    fi
    case "$requested" in
        core|motor|hardware)
            printf '%s\n' "$requested"
            return 0
            ;;
    esac
    if [[ ! "$requested" =~ ^[A-Za-z0-9_-]+$ ]]; then
        # 별칭 조회는 이 값을 sed 식에 넣는다. 걸러내지 않으면 운영자가
        # 거절 사유 대신 sed 의 파싱 오류를 읽게 된다.
        echo "error: unknown ROSY_RUNTIME_MODE '$requested' (expected core, motor, hardware, or a board.yaml alias)" >&2
        return 2
    fi
    if [[ ! -f "$board" ]]; then
        echo "error: board catalog not found: $board" >&2
        return 2
    fi
    local alias
    alias="$(sed -n "s/^  ${requested}: //p" "$board" | head -n 1 | tr -d '\r ')"
    case "$alias" in
        core|motor|hardware)
            printf '%s\n' "$alias"
            return 0
            ;;
    esac
    echo "error: unknown ROSY_RUNTIME_MODE '$requested' (expected core, motor, hardware, or a board.yaml alias)" >&2
    return 2
}

# Map a comma-separated slice set onto a catalog mode. Order does not matter.
# Slices must include core and match a preset exactly; vision/omx/ai are not installable yet.
resolve_slices_to_mode() {
    local requested="${1:-}"
    local board="${2:-}"
    if [[ -z "$requested" || -z "$board" ]]; then
        echo "error: resolve_slices_to_mode requires slices and board.yaml" >&2
        return 2
    fi
    if [[ ! -f "$board" ]]; then
        echo "error: board catalog not found: $board" >&2
        return 2
    fi

    local -a slices=()
    local -A seen=()
    local rest token
    rest="$requested"
    while [[ -n "$rest" ]]; do
        token="${rest%%,*}"
        if [[ "$rest" == *","* ]]; then
            rest="${rest#*,}"
        else
            rest=""
        fi
        token="${token#"${token%%[![:space:]]*}"}"
        token="${token%"${token##*[![:space:]]}"}"
        [[ -n "$token" ]] || continue
        if [[ ! "$token" =~ ^[A-Za-z0-9_-]+$ ]]; then
            echo "error: unknown slice '$token'" >&2
            return 2
        fi
        if [[ -z "${seen[$token]+x}" ]]; then
            seen[$token]=1
            slices+=("$token")
        fi
    done
    if ((${#slices[@]} == 0)); then
        echo "error: resolve_slices_to_mode requires slices and board.yaml" >&2
        return 2
    fi

    local catalog
    catalog="$(awk '
        {
            gsub(/\r/, "")
        }
        /^slices:/ { sec="slices"; next }
        /^presets:/ { sec="presets"; next }
        /^[A-Za-z]/ { sec=""; next }
        sec=="slices" && $1=="required:" {
            sub(/.*\[/, "")
            sub(/\].*/, "")
            gsub(/,/, " ")
            n=split($0, a, " ")
            for (i=1; i<=n; i++) if (a[i] != "") print "REQUIRED", a[i]
            next
        }
        sec=="slices" && $1=="available:" {
            sub(/.*\[/, "")
            sub(/\].*/, "")
            gsub(/,/, " ")
            n=split($0, a, " ")
            for (i=1; i<=n; i++) if (a[i] != "") print "AVAILABLE", a[i]
            next
        }
        sec=="presets" && /^  [A-Za-z0-9_-]+:/ {
            name=$1
            sub(/:/, "", name)
            line=$0
            sub(/.*\[/, "", line)
            sub(/\].*/, "", line)
            gsub(/,/, " ", line)
            print "PRESET", name, line
            next
        }
    ' "$board")"
    if [[ -z "$catalog" ]]; then
        echo "error: board catalog has no slices/presets: $board" >&2
        return 2
    fi

    local -A known=() installable=()
    local -A preset_slices=()
    local kind name
    while read -r kind name rest; do
        case "$kind" in
            REQUIRED|AVAILABLE)
                known["$name"]=1
                ;;
            PRESET)
                preset_slices["$name"]="$rest"
                for token in $rest; do
                    known["$token"]=1
                    installable["$token"]=1
                done
                ;;
        esac
    done <<< "$catalog"

    local has_core=0
    for token in "${slices[@]}"; do
        [[ "$token" == "core" ]] && has_core=1
        if [[ -z "${known[$token]+x}" ]]; then
            echo "error: unknown slice '$token'" >&2
            return 2
        fi
        if [[ -z "${installable[$token]+x}" ]]; then
            echo "error: slice not installable yet: '$token'" >&2
            return 2
        fi
    done
    if ((has_core == 0)); then
        echo "error: slices must include core" >&2
        return 2
    fi

    local wanted listed
    wanted="$(printf '%s\n' "${slices[@]}" | LC_ALL=C sort | awk '{ s=s sep $0; sep="," } END { print s }')"
    for name in "${!preset_slices[@]}"; do
        # shellcheck disable=SC2086
        listed="$(printf '%s\n' ${preset_slices[$name]} | LC_ALL=C sort | awk '{ s=s sep $0; sep="," } END { print s }')"
        if [[ "$wanted" == "$listed" ]]; then
            printf '%s\n' "$name"
            return 0
        fi
    done
    echo "error: slices do not match any installable preset" >&2
    return 2
}
