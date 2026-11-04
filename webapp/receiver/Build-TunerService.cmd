@echo off
rem Rebuilds tuner-service\bin from tuner-service\src (needs the .NET SDK and internet for the NuGet packages, once).
rem Only needed after changing the C# sources: tuner-service\bin already contains the built program.
cd /d "%~dp0tuner-service"
dotnet build TunerService.csproj -c Release -o bin
if errorlevel 1 pause
