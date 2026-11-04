Tuner code from Open Tuner by Tom ZR6TG and contributors
https://github.com/tomvdb/open_tuner - GNU General Public License v3 (see ..\..\LICENSE-GPL-3.0.txt)

Copied from HB9IIU's modified Open Tuner (as shipped with QOCAST 0.1), which added
QocastRxInfo.cs. Changes made for the QOCAST Player:
- FTDIInterface.cs: hw_close() releases the USB ports (it was empty);
  an unused "using FlyleafLib..." line removed.

The own copies of OpenTuner's NimThread.cs and QocastControlServer.cs
(changed more) are in ..\Receiver and ..\Control.
