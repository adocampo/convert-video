#!/bin/bash

# Función para mostrar la ayuda del script
function mostrar_ayuda() {
    echo "Uso: $0 [opciones] archivo1 archivo2 ..."
    echo
    echo "Opciones:"
    echo "  --codec=<codec>   Especifica el códec de video a usar (av1 o h265)."
    echo "  -y, --yes         Acepta automáticamente la transcodificación sin preguntar."
    echo "  -h, --help        Muestra esta ayuda y termina."
    echo
    echo "Este script convierte archivos de video al formato especificado."
    echo "Utiliza HandBrakeCLI para la transcodificación y conserva todas las pistas de audio y subtítulos."
    echo
    echo "Los archivos de entrada pueden incluir expresiones regulares para seleccionar múltiples archivos."
    echo "Por ejemplo: '*.mp4' para seleccionar todos los archivos MP4 en el directorio actual."
    echo
}

# Definir valores por defecto
codec="h265" # Valor por defecto
input_files=()
auto_accept=false

# Parsear argumentos
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --codec=*)
            codec="${1#*=}"
            ;;
        -y|--yes)
            auto_accept=true
            ;;
        -h|--help)
            mostrar_ayuda
            exit 0
            ;;
        *)
            input_files+=("$1")
            ;;
    esac
    shift
done

# Verificar si se proporcionaron archivos de entrada
if [ ${#input_files[@]} -eq 0 ]; then
    echo "No se proporcionaron archivos de entrada."
    exit 1
fi

# Función para generar un nombre de archivo único
generate_unique_filename() {
    local base_name="$1"
    local extension="$2"
    local counter=1

    while [ -e "${base_name}_converted${extension}" ]; do
        if [[ "${base_name}" =~ _converted\(([0-9]+)\)$ ]]; then
            counter=$(( ${BASH_REMATCH[1]} + 1 ))
            base_name="${base_name%_*}_converted(${counter})"
        else
            base_name="${base_name}_converted(${counter})"
        fi
    done

    echo "${base_name}_converted${extension}"
}

# Mostrar la lista de archivos coincidentes
echo "Archivos coincidentes:"
for file in "${input_files[@]}"; do
    echo "$file"
done

# Preguntar si desea continuar con la transcodificación si no se ha especificado --yes o -y
if [ "$auto_accept" = false ]; then
    read -p "¿Desea continuar con la transcodificación? (Sí/No): " answer
    case "$answer" in
        [SsYy]*|[Ss][Íí]*|[Yy][Ee][Ss]*)
            ;;
        *)
            echo "Operación cancelada."
            exit 0
            ;;
    esac
fi

# Continuar con la transcodificación
echo "Iniciando la transcodificación..."

# Bucle para procesar cada archivo coincidente
for input_file in "${input_files[@]}"; do
    if [ ! -f "$input_file" ]; then
        echo "El archivo $input_file no existe. Saltando..."
        continue
    fi

    # Crear el nombre del archivo de salida único
    base_name="${input_file%.*}"
    output_file=$(generate_unique_filename "$base_name" ".mkv")

    if [[ "$codec" == "av1" ]]; then
        echo "Utilizando HandBrakeCLI para transcodificar a AV1."
        # Comando HandBrakeCLI para la transcodificación a AV1 con todas las pistas de audio y subtítulos
        if ! HandBrakeCLI -i "$input_file" -o "$output_file" --preset="AV1 MKV 2160p60 4K" --all-audio --all-subtitles; then
            echo "Error en la transcodificación con HandBrakeCLI."
            exit 1
        fi
    elif [[ "$codec" == "h265" ]]; then
        echo "Utilizando HandBrakeCLI para transcodificar a H.265 NVENC."
        # Comando HandBrakeCLI para la transcodificación a H.265 NVENC con todas las pistas de audio y subtítulos
        if ! HandBrakeCLI -i "$input_file" -o "$output_file" --preset="H.265 NVENC 2160p 4K" --all-audio --all-subtitles; then
            echo "Error en la transcodificación con HandBrakeCLI."
            exit 1
        fi
    else
        echo "Códec no reconocido: $codec. Operación cancelada."
        exit 1
    fi

    echo "Transcodificación completada. Archivo de salida: $output_file"
done

echo "Proceso completo."
