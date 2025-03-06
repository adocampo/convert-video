#!/bin/bash

# Definir colores ANSI
GREEN_COLOR='\033[0;32m'
YELLOW_COLOR='\033[1;33m'
RED_COLOR='\033[0;31m'
RESET_COLOR='\033[0m'
CYAN_COLOR='\033[0;36m'

# Mensajes informativos
function info() {
    echo -e "${GREEN_COLOR}$1${RESET_COLOR}" >&1
}

# Preguntas y advertencias
function pregunta() {
    echo -ne "${YELLOW_COLOR}$1${RESET_COLOR}"
}

# Errores
function error() {
    echo -e "${RED_COLOR}$1${RESET_COLOR}" >&2
}

# Function to show script help
function show_help() {
    echo "Usage: $0 [options] [file1 file2 ...]"
    echo
    echo "Options:"
    echo "  -c, --codec=<codec>       Specify the video codec to use (nvenc_h265 -default-, nvenc_h264, av1 or x265)."
    echo "  -o, --output=<path>       Specify the output directory for converted files."
    echo "  -ap, --audio-passthrough  Pass through original audio tracks"
    echo "  -s, --slow                Use slow encoding speed"
    echo "  -f, --fast                Use fast encoding speed"
    echo "  -n, --normal              Use normal encoding speed (default)"
    echo "  -po, --poweroff           Power off the system after conversion"
    echo "  --find[=<pattern>]        Recursively search for video files in directories matching the pattern or current directory if no pattern is given."
    echo "  -y, --yes                 Automatically accept transcoding without prompts."
    echo "  -si, --source-info        Show source information about a single video file"
    echo "  -v, --verbose             Show verbose output from HandBrakeCLI"
    echo "  -h, --help                Show this help and exit."
    echo
    echo "This script converts video files using HandBrakeCLI and preserves all audio and subtitle tracks."
    echo "When --find is used with a pattern, it searches for video files recursively in directories matching the pattern."
    echo "When --output is used with --find, it preserves the directory structure of input files."
    echo
}

# Default values
codec="nvenc_h265" # set default codec to nvenc_h265, nvenc_h264, av1 or x265
input_files=() # array to store input files
auto_accept=false # flag to automatically accept transcoding without prompts
output_dir="" # variable to store output directory
find_pattern="" # variable to store find pattern
find_flag=false # flag to indicate if find option is used
audio_passthrough=false # flag to indicate if audio passthrough is used
poweroff_flag=false # flag to indicate if poweroff is used
show_source_info=false
verbose=false
encode_speed="normal"  # slow, normal, fast

# Calculate 50% of available threads
total_threads=$(nproc)
threads_to_use=$((total_threads / 2))

# Ensure at least 1 thread is used
if [ "$threads_to_use" -lt 1 ]; then
    threads_to_use=1
fi

echo "Using $threads_to_use threads for transcoding."

# Comprobar dependencias
check_dependency() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Error: Se requiere $1 pero no está instalado."
        exit 1
    fi
}

check_dependency "HandBrakeCLI"
check_dependency "mediainfo"
check_dependency "pv"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -c=*|--codec=*)
            codec="${1#*=}" # Set codec to the next argument
            ;;
        -o=*|--output=*)
            output_dir="${1#*=}" # Set output directory to the next argument
            ;;
        --find=*)
            find_flag=true # Set find flag to true
            find_pattern="${1#*=}" # Set find pattern to the next argument
            ;;
        --find)
            find_flag=true
            if [[ "$2" =~ ^-- ]] || [[ -z "$2" ]]; then  # Caso sin patrón
                find_pattern="*"  # Buscar todos los archivos
            else
                find_pattern="$2"
                shift
            fi
            ;;
        -ap|--audio-passthrough)
            audio_passthrough=true
            ;;
        -po|--poweroff)
            poweroff_flag=true
            ;;
        -y|--yes)
            auto_accept=true
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        -si|--source-info)
            show_source_info=true
            shift
            ;;
        -v|--verbose)
            verbose=true
            shift
            ;;
        -s|--slow)
            encode_speed="slow"
            ;;
        -f|--fast)
            encode_speed="fast"
            ;;
        -n|--normal)
            encode_speed="normal"
            ;;
        *)
            if [[ -d "$1" ]]; then
                echo "Error: Directory '$1' requires --find option"
                exit 1
            elif [[ -f "$1" ]]; then
                input_files+=("$1")
            else
                echo "Error: Invalid input '$1'"
                exit 1
            fi
            ;;
    esac
    shift
done

# If --find is specified, search for video files in directories matching the pattern
if [ "$find_flag" = true ]; then # Check if find flag is specified
    input_files=()
    # Find directories matching the pattern
    while IFS= read -r -d $'\0' dir; do
        # Find video files within each matching directory
        while IFS= read -r -d $'\0' file; do
            input_files+=("$file")
        done < <(find "$dir" -type f \( -name "*.mp4" -o -name "*.ts" -o -name "*.mkv" -o -name "*.avi" \) -print0)
    done < <(find "$(pwd)" -type d -path "$(pwd)/$find_pattern" -print0)
fi

# Check for input files
if [ ${#input_files[@]} -eq 0 ]; then # Check if input files are provided
    echo "No input files provided."
    exit 1
fi

# Check if output directory is specified and is valid
if [ -n "$output_dir" ]; then # Check if output directory is specified
    if [ ! -d "$output_dir" ]; then # Check if output directory exists
        echo "Output directory '$output_dir' does not exist."
        exit 1
    fi
    if [ ! -w "$output_dir" ]; then # Check if output directory is writable
        echo "No write permission in output directory '$output_dir'."
        exit 1
    fi
fi

# Al inicio del script
trap 'limpiar_temporales' SIGINT SIGTERM

# Función de limpieza
limpiar_temporales() {
    echo -e "\n${RED_COLOR}Recibida señal de interrupción. Limpiando...${RESET_COLOR}"
    rm -f "$temp_file" 2>/dev/null
    exit 1
}

# Function to generate a unique final filename
generate_unique_filename() {
    local base_name="$1" # Base name of the file
    local extension="$2" # Extension of the file
    local output_path="$3" # Output directory
    local counter=1 # Counter for unique filename
    local output_file="${output_path}/${base_name}.${extension}" # Output file

    while [ -e "$output_file" ]; do
        if [[ "${base_name}" =~ \([0-9]+\)$ ]]; then
            counter=$(( ${BASH_REMATCH[1]} + 1 ))
            base_name="${base_name%(*}_($counter)"
        else
            base_name="${base_name}_($counter)"
        fi
        output_file="${output_path}/${base_name}.${extension}"
    done

    echo "$output_file"
}

# Display list of matching files
echo "Matching files:"
for file in "${input_files[@]}"; do
    echo "$file"
done

# Prompt mejorado con manejo de Escape y limpieza de línea
if [ "$auto_accept" = false ]; then
    while true; do
        pregunta "¿Continuar con la transcodificación? [S(sí)/N(no)] (por defecto S): "
        read -rs -n1 key
        
        case "$key" in
            $'\e')  # Tecla Escape
                info "\nOperación cancelada por el usuario (Escape)."
                exit 0
                ;;
            ""|"S"|"s"|"Y"|"y")
                echo -e "\n"
                break
                ;;
            "N"|"n")
                info "\nOperación cancelada."
                exit 0
                ;;
            *)
                echo -ne "\r\033[2K"
                error "Opción no válida. Intente nuevamente "
                sleep 0.7
                echo -ne "\r\033[2K"
                ;;
        esac
    done
fi

# Start transcoding process
echo "Starting transcoding..."

# Función de progreso modificada
mostrar_progreso() {
    local input_file="$1"
    local duration
    duration=$(mediainfo --Inform="General;%Duration%" "$input_file" | awk '{printf "%.0f", $1/1000}')
    
    if [ "$duration" -le 0 ]; then
        duration=1
    fi
    
    if $verbose; then
        HandBrakeCLI "${hb_params[@]}"
    else
        # Ejecutar en subshell para manejar redirecciones
        (
            exec 3>&1  # Guardar stdout original
            HandBrakeCLI "${hb_params[@]}" 2>&1 1>&3 | \
                grep --line-buffered -oP "Encoding:.*? \K\d+\.\d+% \(.*? fps, avg .*? fps, ETA \S+\)" | \
                while IFS= read -r line; do
                    percent=$(echo "$line" | cut -d'%' -f1)
                    speed=$(echo "$line" | grep -oP '\d+\.\d+ fps' | head -1)
                    eta=$(echo "$line" | grep -oP 'ETA \S+' | cut -d' ' -f2)
                    echo "$percent $speed $eta"
                done | \
                pv -pet -W -s "$duration" -F "Progreso: %p | Velocidad: %a fps | ETA: %e"
        )
    fi
}

# Función de conversión actualizada
convertir_video() {
    local input_file="$1"
    local temp_file final_output output_subdir
    # Extraer información de resolución
    local resolution
    resolution=$(mediainfo --Inform="Video;%Width%x%Height%" "$input_file")

    # Configurar parámetros de audio según modo
    local -a audio_params=()
    if [ "$show_source_info" = true ]; then
        info "=== Información técnica del archivo fuente ==="
        
        # Información general
        local general_info
        general_info=$(mediainfo --Output=JSON "$input_file" | jq '.media.track[] | select(."@type" == "General")')
        echo -e "Contenedor: $(jq -r '.Format' <<< "$general_info")\nDuración: $(jq -r '.Duration' <<< "$general_info")\nTamaño: $(jq -r '.FileSize' <<< "$general_info") bytes\n"
        
        # Pistas de vídeo
        echo "=== Pistas de vídeo ==="
        mediainfo --Output=JSON "$input_file" | jq -r '
            .media.track[] | 
            select(."@type" == "Video") | 
            [
                "Pista \(.ID)",
                "\(.Width)x\(.Height)",
                "\(.FrameRate | split(".")[0]) fps",
                "\(.Format)",
                "\(.BitRate // .BitRate_Mode // "N/A")"
            ] | join("\t")' | column -t -s $'\t' -N "Pista,Resolución,FPS,Formato,Bitrate"
        
        # Pistas de audio
        echo -e "\n=== Pistas de audio ==="
        mediainfo --Output=JSON "$input_file" | jq -r '
            .media.track[] | 
            select(."@type" == "Audio") | 
            [
                "Pista \(.ID)",
                .Title // "Sin título",
                "\(.Channels) canales",
                "\(.BitRate // .BitRate_Mode // "N/A")",
                .Format
            ] | join("\t")' | column -t -s $'\t' -N "Pista,Título,Canales,Bitrate,Formato"
        
        # Pistas de subtítulos
        echo -e "\n=== Pistas de subtítulos ==="
        mediainfo --Output=JSON "$input_file" | jq -r '
            .media.track[] | 
            select(."@type" == "Text") | 
            [
                "Pista \(.ID)",
                .Title // "Sin título",
                .Format,
                .Forced // "No",
                .Default // "No"
            ] | join("\t")' | column -t -s $'\t' -N "Pista,Título,Formato,Forzado,Por defecto"
        
        exit 0
    elif [ "$audio_passthrough" = true ]; then
        audio_params=(
            "--audio-lang-list" "all"
            "--all-audio"
            "--audio-copy-mask" "eac3,ac3,aac,truehd,dts,dtshd,mp2,mp3,opus,vorbis,flac,alac"
            "--aencoder" "copy"
            "--audio-fallback" "none"
        )
    else
        # Obtener información de cada pista
        mapfile -t audio_info < <(mediainfo --Output=JSON "$input_file" | jq -r '.media.track[] | select(."@type" == "Audio") | [.Channels] | join("|")')
        
        # Inicializar arrays
        local -a mixdown_params=()
        local -a ab_params=()
        local -a encoder_params=()
        local -a track_list=()

        # Contador de pistas
        local track_count=1
        
        for channels in "${audio_info[@]}"; do
            # Determinar mixdown según canales
            case $channels in
                2) mix="stereo"; br=128 ;;
                6|7) mix="5point1"; br=256 ;;
                8) mix="7point1"; br=320 ;;
                *) mix="dpl2"; br=160 ;; # Fallback para canales desconocidos
            esac
            
            # Agregar a arrays
            mixdown_params+=("$mix")
            ab_params+=("$br")
            encoder_params+=("opus")
            track_list+=("$track_count")
            
            ((track_count++))
        done

        # Construir parámetros finales
        audio_params=(
            "--audio" "$(IFS=,; echo "${track_list[*]}")"
            "--aencoder" "$(IFS=,; echo "${encoder_params[*]}")"
            "--ab" "$(IFS=,; echo "${ab_params[*]}")"
            "--mixdown" "$(IFS=,; echo "${mixdown_params[*]}")"
            "--audio-copy-mask" ""
        )
        
        # Si no hay pistas
        if [ ${#audio_info[@]} -eq 0 ]; then
            audio_params=(
                "--audio" "1"
                "--aencoder" "ac3"
                "--ab" "256"
                "--mixdown" "5point1"
                "--audio-copy-mask" ""
            )
        fi
    fi

    # Determine output location y generación de nombres
    if [ -n "$output_dir" ]; then
        local relative_path
        relative_path=$(realpath --relative-to="$(pwd)" "$input_file")
        local relative_dir
        relative_dir=$(dirname "$relative_path")
        output_subdir="${output_dir}/${relative_dir}"
        mkdir -p "$output_subdir" || { echo "Error creando directorio $output_subdir"; return 1; }
        local base_name
        base_name=$(basename "$input_file")
        local extension="${base_name##*.}"
        base_name="${base_name%.*}"
        final_output=$(generate_unique_filename "$base_name" "$extension" "$output_subdir")
        temp_file=$(mktemp --tmpdir="$output_subdir" "${base_name}.tmp.${extension}.XXXXXX") || { echo "Error creando temp file"; return 1; }
    else
        output_subdir=$(dirname "$input_file")
        local base_name
        base_name=$(basename "$input_file")
        local extension="${base_name##*.}"
        base_name="${base_name%.*}"
        final_output=$(generate_unique_filename "${base_name}_converted" "$extension" "$output_subdir")
        temp_file=$(mktemp --tmpdir="$output_subdir" "${base_name}.tmp.${extension}.XXXXXX") || { echo "Error creando temp file"; return 1; }
    fi

    # Configure global HandBrakeCLI parameters
    local -a hb_params=(
        -i "$input_file" # input file
        -o "$temp_file" # temporary file
        --all-subtitles # all subtitles
        -f "mkv" # output format
        "${audio_params[@]}" # audio parameters
    )
    
    case $encode_speed in
        slow)
            hb_params+=(--preset="H.265 MKV 2160p60 4K") # slow preset, highest compression
            ;;
        normal)
            hb_params+=(--preset="H.265 NVENC 2160p 4K") # normal preset, pretty good compression
            ;;
        fast)
            hb_params+=( # fast preset, good compression, quality can be adjusted with -q and -b
                -e "$codec"
                -w "${resolution%x*}" #maintain aspect ratio
                -l "${resolution#*x}" #maintain aspect ratio    
                -q 30 # quality, the lower the better, but at expense of size
                --vb 1000 # video bitrate, the higher the better, but at expense of size
            )
            ;;
    esac
    
    if mostrar_progreso "$input_file"; then
        printf "\r\033[2K[${GREEN_COLOR}✓${RESET_COLOR}] Conversión exitosa\n"
        mv "$temp_file" "$final_output"

        # Extraer los títulos de audio originales (se asume el mismo orden)
        mapfile -t orig_audio_titles < <(mediainfo --Output=JSON "$input_file" | 
            jq -r '.media.track[] | select(."@type"=="Audio") | .Title // "Stereo"')

        # Actualizar los títulos de cada pista de audio en el fichero convertido.
        for ((i=0; i<${#orig_audio_titles[@]}; i++)); do
            audio_track_number=$((i+1))
            mkvpropedit "$final_output" --edit track:a${audio_track_number} --set "name=${orig_audio_titles[i]}"
        done
    else
        printf "\r\033[2K[${RED_COLOR}✗${RESET_COLOR}] Error en la conversión\n"
        rm -f "$temp_file"
        return 1
    fi
}

# Bucle principal: se procesa cada archivo una sola vez
for input_file in "${input_files[@]}"; do
    convertir_video "$input_file" || continue
done

echo "Process complete."

if [ "$poweroff_flag" = true ]; then
    echo -n "Apagando en 10 segundos (presiona Ctrl+C para cancelar)... "
    count=10
    cancelado=false
    # Configuramos el manejador para Ctrl+C
    trap 'cancelado=true' SIGINT
    
    while [ $count -gt 0 ] && ! $cancelado; do
        echo -n "$count "
        sleep 1
        ((count--))
        echo -ne "\r\033[2K"
    done
    
    # Restauramos el manejador por defecto
    trap - SIGINT
    
    if $cancelado; then
        echo -e "\r\033[2KApagado cancelado por el usuario."
        exit 0
    else
        echo "Apagando el sistema..."
        sudo systemctl poweroff
    fi
fi
