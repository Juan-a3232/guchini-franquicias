# SME Automation Platform (nombre por definir)

## Qué es
Plataforma de automatización para PyMEs en Argentina. 
Módulos de IA para ayudar a dueños de negocios a automatizar tareas operativas.

## Stack
- Backend: FastAPI (Python)
- Frontend: HTML/CSS/JS estático
- IA: Groq API con llama-3.3-70b-versatile
- Hosting: Railway
- Excel export: openpyxl

## Módulos actuales
- /franquicias → evaluador de candidatos con scoring por IA (deployado en Railway)

## Módulos planeados
- /facturas → scanner de facturas (fu.do API + Claude Vision)
- /bancario → conciliación bancaria
- /dashboard → vista unificada

## Convenciones
- Endpoints en español
- Archivos de estado persistidos en JSON
- Fondo oscuro en UI, estilo consistente entre módulos
- Cada módulo comparte el mismo backend FastAPI y la misma identidad visual
