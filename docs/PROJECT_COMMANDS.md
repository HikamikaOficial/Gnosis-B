# Ejecutar proyectos de Agente B

Estos comandos usan la cola, los permisos y el circuito de revisión, evidencia e
integración del sistema. Requieren un despliegue válido y una configuración
protegida. La validación con el Worker real sigue pendiente: esta guía no certifica
que el servicio esté instalado en este ordenador.

## Preparación

La configuración debe proceder del escritor canónico `build_operator_config`.
Su entrada `integration_target` identifica la rama donde se incorporará el código.
Si se proporciona, el escritor incluye autorización explícita en la sección
`integration`. Esa autorización pertenece a la configuración protegida; un plan
de tareas no puede concederla. Sin esa sección no se habilita integración.

Conservar el método de autenticación ChatGPT del despliegue. Los comandos no
instalan servicios, no cambian credenciales y no habilitan APIs de pago.

## Plan de ejemplo

Guardar como `proyecto.json`. Mantener los identificadores y `created_at` al
reenviar el mismo plan. Un plan registrado es inmutable.

```json
{
  "schema": "gnosis.project.v1",
  "project_id": "ejemplo",
  "tasks": [
    {
      "brief": {
        "brief_id": "ejemplo--base",
        "title": "Implementar la función base",
        "mission": "Implementar la función descrita en la especificación del proyecto.",
        "source": "manual",
        "created_at": "2026-09-27T00:00:00+00:00"
      },
      "dependencies": []
    },
    {
      "brief": {
        "brief_id": "ejemplo--cliente",
        "title": "Usar la función base",
        "mission": "Conectar la función base con su consumidor y verificar el resultado.",
        "source": "manual",
        "created_at": "2026-09-27T00:00:00+00:00"
      },
      "dependencies": ["ejemplo--base"]
    }
  ]
}
```

## Comandos

Desde el entorno instalado de GNOSIS:

```powershell
gnosis project-submit --config C:\ruta\config-protegida.json --plan C:\ruta\proyecto.json
gnosis project-status --config C:\ruta\config-protegida.json --project ejemplo
gnosis project-run --config C:\ruta\config-protegida.json --project ejemplo --worker controlador-1
```

Registrar y consultar no lanzan agentes. `project-run` retoma el proyecto guardado.
Una tarea dependiente solo empieza después de que su predecesora haya completado
publicación e integración. Un bloqueo no se elimina automáticamente al repetir el
comando. Se conservan los límites de intentos y el trabajo realizado.

La salida JSON distingue tareas completadas, pendientes, en ejecución, bloqueadas
y pendientes de dependencias. Para `project-run`, salida 0 significa proyecto
completo; salida 3 significa que queda trabajo. Consultar o registrar correctamente
devuelve 0 aunque el proyecto todavía no esté terminado.

El supervisor limita cada invocación a 1.000 tareas y comprueba una hora de tiempo
entre tareas; los límites del proceso y del trabajo individual siguen perteneciendo
al circuito de ejecución. Un cierre con una tarea activa necesita que venza su
permiso antes de que otro controlador pueda recuperarla.
