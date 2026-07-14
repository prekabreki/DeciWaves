// Frida hook for HZD Remastered's DirectStorage read path (Strategy B/C of
// docs/runtime-binding-plan.md). Confirmed engine streams via dstorage.dll 1.2.2311.1405.
//
// Captures, per streamed request: the source file path, the PHYSICAL offset and
// compressed size, and (for the first reads of the target stream) a backtrace into
// fullgame.dll -- the lead for walking back to where the stream key is constructed.
//
//   frida -f "<...>/HorizonZeroDawnRemastered.exe" -l tools/hzd_dstorage_hook.js --runtime=v8
//   (or attach: frida -n HorizonZeroDawnRemastered.exe -l tools/hzd_dstorage_hook.js)
//
// NOTE: physical offset != the logical locator offset (133081218). DSAR translates
// logical->physical(compressed). Feed captured (file, physOffset) to the DSAR chunk
// table to recover the logical offset -> locator key. See runbook in the plan doc.

'use strict';

// --- DirectStorage 1.x vtable indices (after IUnknown's QI/AddRef/Release = 0/1/2) ---
const IDX_FACTORY_CREATE_QUEUE = 3;   // IDStorageFactory::CreateQueue
const IDX_FACTORY_OPEN_FILE    = 4;   // IDStorageFactory::OpenFile
const IDX_QUEUE_ENQUEUE_REQUEST = 3;  // IDStorageQueue::EnqueueRequest

// --- DSTORAGE_REQUEST layout (x64), FILE source variant ---
//   @0  DSTORAGE_REQUEST_OPTIONS Options (8)   -- bit0 SourceType: 0=FILE,1=MEMORY
//   @8  Source (union, 24): FILE { IDStorageFile* @8 ; UINT64 Offset @16 ; UINT32 Size @24 }
const OFF_OPTIONS = 0;
const OFF_SRC_FILE_PTR = 8;
const OFF_SRC_OFFSET = 16;
const OFF_SRC_SIZE = 24;

const TARGET = 'package.01.00.core.stream';   // the installed (English) dialogue stream
const filePaths = {};        // IDStorageFile* (string) -> path
let dumpedRawOnce = false;
let backtracesLeft = 8;      // cap backtraces so the log stays readable

function vfn(iface, index) {
  const vtbl = iface.readPointer();
  return vtbl.add(index * Process.pointerSize).readPointer();
}

function hookOpenFile(factory) {
  const addr = vfn(factory, IDX_FACTORY_OPEN_FILE);
  Interceptor.attach(addr, {
    onEnter(args) { this.pathArg = args[1]; this.ppv = args[3]; },  // (this, WCHAR* path, riid, void** ppv)
    onLeave(_ret) {
      try {
        const path = this.pathArg.readUtf16String();
        const file = this.ppv.readPointer();
        filePaths[file.toString()] = path;
      } catch (e) { /* ignore */ }
    },
  });
  console.log('[+] hooked IDStorageFactory::OpenFile @ ' + addr);
}

let queueHooked = false;
function hookEnqueue(queue) {
  if (queueHooked) return;
  const addr = vfn(queue, IDX_QUEUE_ENQUEUE_REQUEST);
  Interceptor.attach(addr, {
    onEnter(args) {
      const req = args[1];                          // (this, const DSTORAGE_REQUEST*)
      try {
        const options = req.add(OFF_OPTIONS).readU64();
        const isFile = (options.and(1)).equals(0);
        if (!isFile) return;
        const filePtr = req.add(OFF_SRC_FILE_PTR).readPointer();
        const path = filePaths[filePtr.toString()] || ('<file ' + filePtr + '>');
        if (path.indexOf(TARGET) < 0) return;       // only the dialogue stream

        const offset = req.add(OFF_SRC_OFFSET).readU64();
        const size = req.add(OFF_SRC_SIZE).readU32();
        console.log('[READ] ' + path.split(/[\\/]/).pop() +
                    '  physOffset=' + offset + ' (0x' + offset.toString(16) + ')' +
                    '  size=' + size);

        if (!dumpedRawOnce) {                        // verify struct offsets once
          dumpedRawOnce = true;
          console.log('[raw DSTORAGE_REQUEST first 48B] ' + hexdump(req, { length: 48, ansi: false }));
        }
        if (backtracesLeft > 0) {
          backtracesLeft--;
          const bt = Thread.backtrace(this.context, Backtracer.ACCURATE)
                           .map(DebugSymbol.fromAddress).join('\n    ');
          console.log('  backtrace:\n    ' + bt);
        }
      } catch (e) { console.log('[enqueue parse error] ' + e); }
    },
  });
  queueHooked = true;
  console.log('[+] hooked IDStorageQueue::EnqueueRequest @ ' + addr);
}

function hookCreateQueue(factory) {
  const addr = vfn(factory, IDX_FACTORY_CREATE_QUEUE);
  Interceptor.attach(addr, {
    onEnter(args) { this.ppv = args[3]; },          // (this, desc, riid, void** ppv)
    onLeave(_ret) {
      try { hookEnqueue(this.ppv.readPointer()); } catch (e) { /* ignore */ }
    },
  });
  console.log('[+] hooked IDStorageFactory::CreateQueue @ ' + addr);
}

const getFactory = Module.findExportByName('dstorage.dll', 'DStorageGetFactory');
if (!getFactory) {
  console.log('[!] DStorageGetFactory not found yet; is dstorage.dll loaded? Try attaching after launch.');
} else {
  Interceptor.attach(getFactory, {                  // HRESULT DStorageGetFactory(riid, void** ppv)
    onEnter(args) { this.ppv = args[1]; },
    onLeave(_ret) {
      try {
        const factory = this.ppv.readPointer();
        hookOpenFile(factory);
        hookCreateQueue(factory);
      } catch (e) { console.log('[factory hook error] ' + e); }
    },
  });
  console.log('[+] hooked DStorageGetFactory @ ' + getFactory + ' -- waiting for factory creation');
}
