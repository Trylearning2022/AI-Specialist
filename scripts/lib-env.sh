# Nạp .env theo đúng cú pháp của Docker Compose (KEY=giá trị, giá trị có thể chứa dấu cách, có/không ngoặc),
# không thực thi nội dung tệp như lệnh shell. Dùng: . scripts/lib-env.sh; load_env .env
load_env() {
  local f=${1:-.env} line k v
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    [[ $line =~ ^[[:space:]]*(#|$) ]] && continue
    [[ $line =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    k=${BASH_REMATCH[1]}; v=${BASH_REMATCH[2]}
    if [[ $v =~ ^\"(.*)\"[[:space:]]*(#.*)?$ ]] || [[ $v =~ ^\'(.*)\'[[:space:]]*(#.*)?$ ]]; then
      v=${BASH_REMATCH[1]}
    else
      v=${v%%[[:space:]]#*}; v=${v%"${v##*[![:space:]]}"}
    fi
    export "$k=$v"
  done < "$f"
}
