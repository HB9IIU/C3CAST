@echo off
rem ===========================================================================
rem  build_c3cast_ffmpeg_vvc.bat - the SIMPLE shareable FFmpeg for C3CAST: H.265 (x265, NVENC), H.266 (VVenC), native AAC.
rem
rem  GPL, no non-free parts, no fdk-aac, no x264. Deliberately small: no SRT, no Intel oneVPL, no SDL2/ffplay, no AMD AMF,
rem  no CUDA decoding, no MediaFoundation, no Schannel (C3CAST needs none of them), so the list of libraries that must be
rem  documented stays short: x265, VVenC, FreeType, HarfBuzz, Fontconfig, zlib, bzip2, liblzma, libiconv and the NVIDIA
rem  ffnvcodec headers. Giving it to others also means giving the source of FFmpeg, x265 and VVenC with it.
rem
rem  Put this file NEXT TO media-autobuild_suite.bat (C:\mabs) and run it. The suite builds in its own
rem  window; when that window says it is finished, run STEP 2: finish_datv_ffmpeg_free_H266.bat.
rem
rem  Before it starts, the current C:\mabs\local64\bin-video is copied to C:\mabs\h266-encoder-build
rem  (only once, never overwritten): the suite writes its result to bin-video, over what is there.
rem  Do not run another media-autobuild_suite build at the same time (C3CAST uses the same suite).
rem ===========================================================================

setlocal
cd /d "%~dp0"

if not exist media-autobuild_suite.bat (
    echo media-autobuild_suite.bat not found next to this file.
    echo Put build_datv_ffmpeg_free_H266.bat in the suite folder, e.g. C:\mabs
    pause
    exit /b 1
)

if not exist build mkdir build

rem --- Keep the current build, once ------------------------------------------------
if exist local64\bin-video\ffmpeg.exe (
    if not exist h266-encoder-build (
        echo Keeping the current ffmpeg/ffplay/ffprobe in h266-encoder-build ...
        mkdir h266-encoder-build
        copy /y local64\bin-video\ffmpeg.exe  h266-encoder-build >nul
        copy /y local64\bin-video\ffplay.exe  h266-encoder-build >nul
        copy /y local64\bin-video\ffprobe.exe h266-encoder-build >nul
    )
)

rem --- Use half the logical processors for compiling (at least 1) -----------
set /a CORES=%NUMBER_OF_PROCESSORS%/2
if %CORES% LSS 1 set CORES=1

rem --- FFmpeg source: latest development version -----------------------------
set FFMPEG_PATH=https://code.ffmpeg.org/FFmpeg/FFmpeg.git

rem --- Answers to all suite questions (1 = Yes, 2 = No unless noted) -------
rem     license2=3 is GPL. x2653=1 libx265, vvenc=1 libvvenc. fdkaac=2 and x2643=2: not wanted.
(
echo [compiler list]
echo license2=3
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
echo vvenc=1
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
echo deleteSource=1
echo strip=1
echo pack=2
echo logging=1
echo updateSuite=2
echo timeStamp=2
echo ccache=2
echo noMintty=2
echo ffmpegPath=%FFMPEG_PATH%
echo pkgUpdateTime=86400
) > build\media-autobuild_suite.ini

rem --- FFmpeg configure options (the suite uses this as the COMPLETE list) ---
(
echo # C3CAST - simple shareable FFmpeg, GPL, with libx265 and libvvenc
echo # Lines starting with # are ignored
echo.
echo # Built-ins - Windows / hardware
echo --disable-autodetect
echo --enable-ffnvcodec
echo --enable-nvenc
echo --enable-d3d11va
echo --enable-dxva2
echo --enable-zlib
echo --enable-bzlib
echo --enable-lzma
echo --enable-iconv
echo.
echo # External libraries
echo --disable-debug
echo --enable-gpl
echo --enable-libx265
echo --enable-libvvenc
echo.
echo # Text overlays - drawtext filter, e.g. callsign on camera pictures
echo --enable-libfreetype
echo --enable-libharfbuzz
echo --enable-fontconfig
) > build\ffmpeg_options.txt

rem --- Safety check: nothing non-free in the list, and what we need is in it -
findstr /i /c:"nonfree" /c:"fdk" /c:"x264" /c:"sdl2" /c:"libsrt" /c:"libvpl" /c:"schannel" build\ffmpeg_options.txt >nul && goto :optfail
findstr /x /c:"--enable-libvvenc" build\ffmpeg_options.txt >nul || goto :optfail
findstr /x /c:"--enable-libx265" build\ffmpeg_options.txt >nul || goto :optfail
findstr /x /c:"--enable-gpl" build\ffmpeg_options.txt >nul || goto :optfail

rem --- Empty mpv options file, so the suite does not stop to ask about it ---
if not exist build\mpv_options.txt (
    echo # mpv is not built for QOCAST> build\mpv_options.txt
)

echo.
echo Simple shareable build: answers and FFmpeg options written to %CD%\build
echo Starting media-autobuild_suite ... when its window says it is finished,
echo run finish_datv_ffmpeg_free_H266.bat ^(STEP 2^).
echo.
call media-autobuild_suite.bat
endlocal
exit /b 0

:optfail
echo.
echo ERROR: build\ffmpeg_options.txt does not have the expected free option list.
echo The suite was NOT started. Please report this.
pause
endlocal
exit /b 1
