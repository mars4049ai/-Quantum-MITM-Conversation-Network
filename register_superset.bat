@echo off
:: ============================================================
:: register_superset.bat
:: Creates an admin user in Apache Superset and initialises it.
::
:: Usage (all arguments optional):
::   register_superset.bat [username] [email] [password]
::
:: Defaults (used when arguments are not provided):
::   username : admin
::   email    : admin@admin.com
::   password : postgres123
::
:: Example — custom credentials:
::   register_superset.bat myuser myuser@example.com mypassword
::
:: Example — use defaults:
::   register_superset.bat
:: ============================================================

SET "SS_USER=%~1"
SET "SS_EMAIL=%~2"
SET "SS_PASS=%~3"

IF "%SS_USER%"=="" SET "SS_USER=admin"
IF "%SS_EMAIL%"=="" SET "SS_EMAIL=admin@admin.com"
IF "%SS_PASS%"=="" SET "SS_PASS=postgres123"

echo.
echo [Superset] Registering admin user...
echo   Username : %SS_USER%
echo   Email    : %SS_EMAIL%
echo.

docker exec -it superset superset fab create-admin ^
    --username "%SS_USER%" ^
    --firstname Superset ^
    --lastname Admin ^
    --email "%SS_EMAIL%" ^
    --password "%SS_PASS%"

echo.
echo [Superset] Running database upgrade...
docker exec -it superset superset db upgrade

echo.
echo [Superset] Loading examples...
docker exec -it superset superset load_examples

echo.
echo [Superset] Initialising roles and permissions...
docker exec -it superset superset init

echo.
echo ============================================================
echo  Done! Open http://localhost:8088 and log in with:
echo    Username : %SS_USER%
echo    Password : %SS_PASS%
echo ============================================================
echo.
