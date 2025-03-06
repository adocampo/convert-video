#!/bin/bash
# filepath: /home/malevolent/development/scripts/convert-video-ng/extract-audio.sh
# Script de conversión MKV que permite seleccionar pistas de audio y subtítulos.

# Variable global (por defecto sin debug)
DEBUG=0

# Función para imprimir debug si DEBUG está activado
debug() {
    if [ "$DEBUG" -eq 1 ]; then
        echo "$@" >&2
    fi
}

mostrar_ayuda() {
    echo -e "\nUso: $0 [-a idiomas_audio] [-s idiomas_subs] archivo.mkv"
    echo "Ejemplo: $0 -a=es,cat,jpn -s=es archivo.mkv"
    echo "Los códigos de idioma son case-insensitive (ej: ES = es = spa)"
    echo "Si no se especifica -s, se preguntará de forma interactiva y se permitirá omitir."
    echo "Si no se especifica -a se preguntará obligatoriamente."
    echo "Formatos soportados: .mkv, .webm, .mp4"
    exit 0
}

verificar_dependencias() {
    local faltantes=()
    for cmd in mkvmerge mediainfo jq; do
        if (! command -v "$cmd" &> /dev/null); then
            faltantes+=("$cmd")
        fi
    done

    if [ ${#faltantes[@]} -gt 0 ]; then
        echo "ERROR: Faltan dependencias esenciales:" >&2
        for c in "${faltantes[@]}"; do
            case $c in
                jq) echo "- jq (necesario para procesar JSON)" ;;
                mkvmerge) echo "- mkvtoolnix (paquete que contiene mkvmerge)" ;;
                *) echo "- $c" ;;
            esac
        done
        exit 1
    fi
}

extraer_metadatos() {
    local tipo=$1
    debug "Entrando en extraer_metadatos con tipo=$tipo"
    local metadata_output
    metadata_output=$(jq -r --arg tipo "$tipo" '
        .tracks[] | select(.type == $tipo) |
        "\(.id) \((.properties.language // "und") | ascii_downcase | sub("-.*"; "")) \(.properties.track_name // "")"
    ' <<< "$METADATA")
    debug "Salida de jq en extraer_metadatos: '$metadata_output'"
    echo "$metadata_output"
}

# Función para seleccionar pistas
seleccionar_idiomas() {
    local tipo=$1
    shift
    if [[ "$tipo" == "audio" ]]; then
        # Preparar lista de pistas de audio disponibles (por ID) y sus títulos
        local -a available_ids=()
        declare -A track_titles=()
        for track in "$@"; do
            IFS=' ' read -r id lang title <<< "$track"
            available_ids+=("$id")
            track_titles["$id"]="$title"
        done

        # Si se ha especificado el parámetro -a, interpretar sus valores como IDs
        if [ ${#AUDIO_LANG_PARAM[@]} -gt 0 ]; then
            local -a selected_ids=()
            for param in "${AUDIO_LANG_PARAM[@]}"; do
                for id in "${available_ids[@]}"; do
                    if [[ "$id" == "$param" ]]; then
                        selected_ids+=("$id")
                    fi
                done
            done
            if [ ${#selected_ids[@]} -eq 0 ]; then
                echo "No se encontraron coincidencias automáticas para audio, se entra en modo interactivo." >&2
            else
                echo "${selected_ids[@]}"
                return
            fi
        fi

        # Modo interactivo obligatorio para audio
        while true; do
            echo -e "\n=== Selección de audio ===" >&2
            echo "Pistas disponibles:" >&2
            for id in "${available_ids[@]}"; do
                echo "- [$id] ${track_titles[$id]}" >&2
            done
            # Lee una línea y luego divide por comas
            read -rp "Introduce los números de las pistas (separados por comas): " input_line
            IFS=',' read -ra input <<< "$input_line"
            local -a selected_ids=()
            for sel in "${input[@]}"; do
                local trimmed
                trimmed=$(echo "$sel" | xargs)
                for id in "${available_ids[@]}"; do
                    if [[ "$id" == "$trimmed" ]]; then
                        selected_ids+=("$id")
                    fi
                done
            done
            if [ ${#selected_ids[@]} -gt 0 ]; then
                echo "${selected_ids[@]}"
                break
            else
                echo "Error: Debes seleccionar al menos una pista de audio." >&2
            fi
        done

    elif [[ "$tipo" == "subtítulos" ]]; then
        # Preparar lista de pistas de subtítulos disponibles (por ID) y sus títulos
        local -a available_ids=()
        declare -A track_titles=()
        for track in "$@"; do
            IFS=' ' read -r id lang trackname <<< "$track"
            available_ids+=("$id")
            track_titles["$id"]="$trackname"
        done

        # Si se ha especificado el parámetro -s, interpretar sus valores como IDs
        if [ ${#SUBS_LANG_PARAM[@]} -gt 0 ]; then
            local -a selected_ids=()
            for param in "${SUBS_LANG_PARAM[@]}"; do
                for id in "${available_ids[@]}"; do
                    if [[ "$id" == "$param" ]]; then
                        selected_ids+=("$id")
                    fi
                done
            done
            if [ ${#selected_ids[@]} -eq 0 ]; then
                echo "No se encontraron coincidencias automáticas para subtítulos, se entra en modo interactivo." >&2
            else
                echo "${selected_ids[@]}"
                return
            fi
        fi

        # Modo interactivo obligatorio para subtítulos
        while true; do
            echo -e "\n=== Selección de subtítulos ===" >&2
            echo "Pistas disponibles:" >&2
            for id in "${available_ids[@]}"; do
                echo "- [$id] ${track_titles[$id]}" >&2
            done
            read -rp "Introduce los números de las pistas de subtítulos (separados por comas, o presiona ENTER para omitir): " input_line
            # Si se presiona ENTER, se devuelve vacío (se omiten los subs)
            if [ -z "$input_line" ]; then
                echo ""
                return
            fi
            IFS=',' read -ra input <<< "$input_line"
            local -a selected_ids=()
            for sel in "${input[@]}"; do
                local trimmed
                trimmed=$(echo "$sel" | xargs)
                for id in "${available_ids[@]}"; do
                    if [[ "$id" == "$trimmed" ]]; then
                        selected_ids+=("$id")
                    fi
                done
            done
            if [ ${#selected_ids[@]} -gt 0 ]; then
                echo "${selected_ids[@]}"
                break
            else
                echo "Error: Debes seleccionar al menos una pista de subtítulos o presiona ENTER para omitir." >&2
            fi
        done
    fi
}

procesar_parametros() {
    # Buscar --debug manualmente en los argumentos y quitarlo
    for arg in "$@"; do
        if [[ "$arg" == "--debug" ]]; then
            DEBUG=1
        fi
    done

    # Se usan -a para audio y -s para subtítulos
    while getopts ":a:s:h" opt; do
        case $opt in
            a) IFS=',' read -ra AUDIO_LANG_PARAM <<< "$OPTARG" ;;
            s) IFS=',' read -ra SUBS_LANG_PARAM <<< "$OPTARG" ;;
            h) mostrar_ayuda ;;
            \?) echo "Opción inválida: -$OPTARG" >&2; exit 1 ;;
            :) echo "Opción -$OPTARG requiere un argumento." >&2; exit 1 ;;
        esac
    done
    shift $((OPTIND-1))
    
    if [ $# -eq 0 ]; then
        echo "Error: Se requiere archivo de entrada" >&2
        mostrar_ayuda
    fi
    INPUT="$1"
    OUTPUT="${INPUT%.*}_converted.mkv"
    
    if [ ! -f "$INPUT" ]; then
        echo "Error: Archivo no encontrado: $INPUT" >&2
        exit 1
    fi
    debug "DEBUG: INPUT='$INPUT', OUTPUT='$OUTPUT'"
}

main() {
    verificar_dependencias
    procesar_parametros "$@"
    
    debug "Extrayendo metadatos con mkvmerge -J '$INPUT'"
    METADATA=$(mkvmerge -J "$INPUT" || { echo "Error al leer metadatos"; exit 1; })
    debug "Metadatos extraídos (longitud=${#METADATA}): '$METADATA'"

    # Leer pistas línea a línea en arrays
    mapfile -t AUDIO_TRACKS < <(extraer_metadatos audio)
    debug "AUDIO_TRACKS='${AUDIO_TRACKS[@]}'"

    mapfile -t SUBS_TRACKS < <(extraer_metadatos subtitles)
    debug "SUBS_TRACKS='${SUBS_TRACKS[@]}'"

    AUDIO_LANGS=($(seleccionar_idiomas "audio" "${AUDIO_TRACKS[@]}"))
    debug "AUDIO_LANGS='${AUDIO_LANGS[@]}'"

    SUBS_LANGS=($(seleccionar_idiomas "subtítulos" "${SUBS_TRACKS[@]}"))
    debug "SUBS_LANGS='${SUBS_LANGS[@]}'"

    # Construir comando mkvmerge: Se mantiene el vídeo y se extrae audio y subtítulos según selección
    mkvmerge_cmd=("mkvmerge" "-o" "$OUTPUT")
    
    # Para audio se conserva (ya que se eligen por ID en la selección)
    selected_audio_ids=("${AUDIO_LANGS[@]}")
    if [ ${#selected_audio_ids[@]} -gt 0 ]; then
        audio_tracks=$(IFS=, ; echo "${selected_audio_ids[*]}")
        mkvmerge_cmd+=("--audio-tracks" "$audio_tracks")
    fi

    # Para subtítulos usar directamente la selección (por ID) devuelta por la función
    selected_subs_ids=("${SUBS_LANGS[@]}")
    if [ ${#selected_subs_ids[@]} -gt 0 ]; then
        subs_tracks=$(IFS=, ; echo "${selected_subs_ids[*]}")
        mkvmerge_cmd+=("--subtitle-tracks" "$subs_tracks")
    fi

    # Extraer los IDs de las pistas de vídeo desde METADATA (suponiendo que provienen de 0, el índice del fichero)
    video_ids=( $(jq -r '.tracks[] | select(.type=="video") | .id' <<< "$METADATA") )

    # Construir la lista de track_order:
    # Primero se agregan las pistas de video, luego las de audio (en el orden elegido por el usuario)
    # y por último los subtítulos (en su orden original)
    track_order=""

    # Agregar vídeos (se mantienen en su orden original)
    for vid in "${video_ids[@]}"; do
        if [ -z "$track_order" ]; then
            track_order="0:$vid"
        else
            track_order+=",0:$vid"
        fi
    done

    # Agregar pistas de audio en el orden indicado por el usuario
    for aid in "${selected_audio_ids[@]}"; do
        track_order+=",0:$aid"
    done

    # Agregar pistas de subtítulos en orden original
    for track in "${SUBS_TRACKS[@]}"; do
        IFS=' ' read -r id lang <<< "$track"
        track_order+=",0:$id"
    done

    mkvmerge_cmd+=("--track-order" "$track_order")

    # No se omiten el vídeo, ni capítulos ni attachments (se conservará el vídeo principal)
    mkvmerge_cmd+=("--no-chapters" "--no-attachments" "$INPUT")

    echo -e "\nIniciando conversión..." >&2
    if ! "${mkvmerge_cmd[@]}" >/dev/null 2>&1; then
        echo "Error crítico en la conversión. Comando ejecutado:" >&2
        echo "${mkvmerge_cmd[@]}" >&2
        exit 1
    fi

    echo -e "\nConversión exitosa: $OUTPUT" >&2
    echo "=== Resumen del archivo convertido ===" >&2
    mediainfo "$OUTPUT" | grep -P '(Track type|Language|Title|Codec)' | sed -E 's/ {2,}//'

    # Post-proceso: marcar la primera pista de audio (según la selección) como default y el resto como no default.
    # Se asume que en el archivo de salida las pistas de audio se numeran como track:a1, track:a2, etc.
    if [ ${#selected_audio_ids[@]} -gt 0 ]; then
        # Marcar la primera pista de audio como default
        mkvpropedit "$OUTPUT" --edit track:a1 --set flag-default=1

        # Para el resto de pistas de audio, desactivar el flag default
        for i in $(seq 2 ${#selected_audio_ids[@]}); do
            mkvpropedit "$OUTPUT" --edit track:a$i --set flag-default=0
        done
    fi
}

main "$@"
