@echo off
rem C3CAST: GPLv3-or-later FFmpeg, x265 + NVENC + native AAC, no FDK/nonfree.
rem Run /check for prerequisites only; /prepare for config only; /verify for binary checks.
rem See build_c3cast_ffmpeg_README.md for release/source obligations.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if not exist media-autobuild_suite.bat goto :missing
if /i "%~1"=="/verify" goto :verify
if not exist msys64\usr\bin\bash.exe goto :missing
if /i "%~1"=="/check" (
    echo Prerequisites found. No configuration changed and no build started.
    exit /b 0
)
if not "%~1"=="" if /i not "%~1"=="/prepare" exit /b 2
if not exist build mkdir build
if errorlevel 1 exit /b 1
rem Save original settings once; never overwrite the backup on later runs.
if exist build\media-autobuild_suite.ini if not exist build\c3cast-original-suite.ini copy /y build\media-autobuild_suite.ini build\c3cast-original-suite.ini >nul
if exist build\ffmpeg_options.txt if not exist build\c3cast-original-ffmpeg_options.txt copy /y build\ffmpeg_options.txt build\c3cast-original-ffmpeg_options.txt >nul
set /a CORES=%NUMBER_OF_PROCESSORS%/2
if %CORES% LSS 1 set CORES=1
set "FFMPEG_PATH=https://code.ffmpeg.org/FFmpeg/FFmpeg.git"
(
echo [compiler list]
echo license2=2
echo standalone=2
echo av1an=2
echo vpx2=2
echo aom=2
echo rav1e=2
echo dav1d=2
echo libavif=2
echo libheif=2
echo jpegxl=2
echo x2643=2
echo x2653=1
echo other265=2
echo svthevc=2
echo xvc=2
echo uvg266=2
echo vvenc=2
echo vvdec=2
echo svtav1=2
echo svtvp9=2
echo flac=2
echo fdkaac=2
echo faac=2
echo exhale=2
echo mediainfo=2
echo soxB=2
echo ffmpegB2=1
echo ffmpegUpdate=1
echo ffmpegChoice=1
echo ffmpegKeepLegacyOpts=2
echo mp4box=2
echo rtmpdump=2
echo mpv=2
echo vlc=2
echo bmx=2
echo curl=2
echo cyanrip2=2
echo ripgrep=2
echo jq=2
echo jo=2
echo dssim=2
echo gifski=3
echo avs2=2
echo dovitool=2
echo hdr10plustool=2
echo zlib=6
echo CC=2
echo cores=%CORES%
echo deleteSource=2
echo strip=1
echo pack=2
echo logging=1
echo updateSuite=2
echo timeStamp=2
echo ccache=2
echo noMintty=1
echo ffmpegPath=%FFMPEG_PATH%
echo pkgUpdateTime=86400
) > build\media-autobuild_suite.ini

(
echo --disable-autodetect
echo --enable-gpl
echo --enable-version3
echo --disable-nonfree
echo --disable-libfdk-aac
echo --disable-libx264
echo --enable-libx265
echo --enable-ffnvcodec
echo --enable-nvenc
echo --enable-d3d11va
echo --enable-dxva2
echo --enable-schannel
echo --enable-zlib
echo --enable-bzlib
echo --enable-lzma
echo --enable-iconv
echo --enable-libfreetype
echo --enable-libharfbuzz
echo --enable-fontconfig
echo --enable-encoder=aac
echo --enable-indev=dshow
echo --disable-debug
) > build\ffmpeg_options.txt

if not exist build\mpv_options.txt echo # mpv is disabled>build\mpv_options.txt
if /i "%~1"=="/prepare" (
    echo Configuration prepared. No build started.
    exit /b 0
)
echo Building GPL FFmpeg. Sources are retained in build; do not delete them.
call media-autobuild_suite.bat
if errorlevel 1 exit /b 1
:verify
set "FFBIN=%~dp0local64\bin-video\ffmpeg.exe"
if not exist "%FFBIN%" (
    echo ERROR: Expected binary missing: %FFBIN%
    exit /b 1
)
"%FFBIN%" -hide_banner -buildconf >build\c3cast-buildconf.txt 2>&1
if errorlevel 1 exit /b 1
findstr /c:"--enable-nonfree" /c:"--enable-libfdk-aac" build\c3cast-buildconf.txt >nul && goto :bad
findstr /c:"--enable-gpl" build\c3cast-buildconf.txt >nul || goto :bad
rem GPLv2-or-later is also valid; MABS may omit --enable-version3.
"%FFBIN%" -hide_banner -encoders >build\c3cast-encoders.txt 2>&1
if errorlevel 1 exit /b 1
findstr /c:"libfdk_aac" build\c3cast-encoders.txt >nul && goto :bad
for %%E in (libx265 hevc_nvenc aac) do (
    findstr /c:" %%E " build\c3cast-encoders.txt >nul || goto :bad
)
"%FFBIN%" -hide_banner -loglevel error -f lavfi -i testsrc2=size=320x180:rate=10 -f lavfi -i sine=frequency=1000:sample_rate=48000 -t 1 -c:v libx265 -preset ultrafast -pix_fmt yuv420p -c:a aac -profile:a aac_low -b:a 64k -f null -
if errorlevel 1 goto :bad
"%FFBIN%" -L >build\c3cast-license.txt 2>&1
echo Build checks passed. This is NOT a complete distribution licence audit.
echo Keep matching sources, patches, dependency notices and build instructions for release.
echo C3CAST still needs native AAC-LC settings instead of libfdk_aac / HE-AAC.
exit /b 0
:bad
echo ERROR: Binary configuration or encoder checks failed. Do not distribute it.
exit /b 1
:missing
echo ERROR: Run this file inside an initialized MABS folder such as C:\mabs.
exit /b 1
