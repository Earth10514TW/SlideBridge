#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

#include <windows.h>
#include <ole2.h>
#include <oleidl.h>
#include <objbase.h>
#include <oleauto.h>

#include <algorithm>
namespace Gdiplus {
  using std::min;
  using std::max;
}
#include <gdiplus.h>

#include <cwchar>
#include <iostream>
#include <iterator>
#include <string>
#include <utility>

#include "save_sequence.h"

namespace {

constexpr wchar_t kOriginProgId[] = L"Origin95.Graph";
constexpr wchar_t kWindowClass[] = L"SlideBridgeOriginHost";
constexpr wchar_t kWindowTitle[] = L"SlideBridge - Origin host";
constexpr int kOpenButton = 1001;
constexpr int kSaveButton = 1002;
constexpr int kSaveCloseButton = 1003;
constexpr int kStatusControl = 1004;
constexpr int kDiscardCloseButton = 1005;

constexpr CLSID kPngEncoderClsid = {
    0x557cf406, 0x1a04, 0x11d3, {0x9a, 0x73, 0x00, 0x00, 0xf8, 0x1e, 0xf3, 0x2e}};

std::wstring GetBasePathWithoutExt(const std::wstring& path) {
  size_t lastDot = path.find_last_of(L'.');
  size_t lastSlash = path.find_last_of(L"/\\");
  if (lastDot != std::wstring::npos && (lastSlash == std::wstring::npos || lastDot > lastSlash)) {
    return path.substr(0, lastDot);
  }
  return path;
}

std::wstring GetFilename(const std::wstring& path) {
  size_t lastSlash = path.find_last_of(L"/\\");
  if (lastSlash != std::wstring::npos) {
    return path.substr(lastSlash + 1);
  }
  return path;
}

std::wstring GetDirectoryOf(const std::wstring& path) {
  size_t lastSlash = path.find_last_of(L"/\\");
  if (lastSlash == std::wstring::npos) {
    return std::wstring();
  }
  return path.substr(0, lastSlash);
}

bool FileExists(const std::wstring& path) {
  const DWORD attributes = GetFileAttributesW(path.c_str());
  return attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY);
}

// Turns an HRESULT built by HRESULT_FROM_WIN32 back into a readable Win32
// error name. Without this the caller only sees 0x80070043, which is far less
// useful than "ERROR_BAD_NET_NAME".
std::wstring Win32ErrorText(HRESULT hr) {
  const unsigned long raw = static_cast<unsigned long>(hr);
  if ((raw & 0xFFFF0000UL) != 0x80070000UL) {
    return L"";
  }
  const DWORD code = static_cast<DWORD>(raw & 0xFFFFUL);
  switch (code) {
    case ERROR_FILE_EXISTS:
    case ERROR_ALREADY_EXISTS:
      return L" [ERROR_ALREADY_EXISTS: the output file is already there]";
    case ERROR_BAD_NET_NAME:
      return L" [ERROR_BAD_NET_NAME: this path is not reachable from the VM]";
    case ERROR_PATH_NOT_FOUND:
      return L" [ERROR_PATH_NOT_FOUND]";
    case ERROR_FILE_NOT_FOUND:
      return L" [ERROR_FILE_NOT_FOUND]";
    case ERROR_ACCESS_DENIED:
      return L" [ERROR_ACCESS_DENIED]";
    case ERROR_SHARING_VIOLATION:
      return L" [ERROR_SHARING_VIOLATION]";
    default:
      return L" [Win32 error " + std::to_wstring(static_cast<unsigned long>(code)) + L"]";
  }
}

void Log(const std::wstring& message) {
  std::wcout << message << std::endl;
}

void LogHr(const std::wstring& operation, HRESULT hr) {
  std::wcout << operation << L": HRESULT=0x" << std::hex
             << static_cast<unsigned long>(hr) << std::dec << Win32ErrorText(hr)
             << std::endl;
}

// CopyFileW with bFailIfExists, reporting the real failure reason. The previous
// message asserted "output must not already exist" regardless of cause, which
// sent a genuine ERROR_BAD_NET_NAME hunt in the wrong direction.
HRESULT CopyInputToOutput(const std::wstring& input, const std::wstring& output) {
  if (CopyFileW(input.c_str(), output.c_str(), TRUE)) {
    return S_OK;
  }
  HRESULT hr = HRESULT_FROM_WIN32(GetLastError());
  Log(L"CopyFileW failed (the output file must not already exist):");
  Log(L"  input : " + input);
  Log(L"  output: " + output);
  LogHr(L"CopyFileW", hr);
  return hr;
}

std::wstring GuidText(REFCLSID clsid) {
  wchar_t buffer[64]{};
  if (StringFromGUID2(clsid, buffer, static_cast<int>(std::size(buffer))) == 0) {
    return L"{invalid-guid}";
  }
  return buffer;
}

bool IsEqualGuid(REFCLSID left, REFCLSID right) {
  return IsEqualCLSID(left, right) != FALSE;
}

HRESULT ReadRootClsid(IStorage* storage, CLSID* clsid) {
  if (!storage || !clsid) {
    return E_INVALIDARG;
  }
  STATSTG stat{};
  HRESULT hr = storage->Stat(&stat, STATFLAG_NONAME);
  if (FAILED(hr)) {
    return hr;
  }
  *clsid = stat.clsid;
  return S_OK;
}

HRESULT OpenStorage(const std::wstring& path, DWORD mode, IStorage** result) {
  if (!result) {
    return E_INVALIDARG;
  }
  *result = nullptr;
  return StgOpenStorage(path.c_str(), nullptr, mode, nullptr, 0, result);
}

HRESULT ParseClsid(const std::wstring& value, CLSID* clsid) {
  if (!clsid) {
    return E_INVALIDARG;
  }
  return CLSIDFromString(const_cast<LPOLESTR>(value.c_str()), clsid);
}

// This check deliberately uses only the storage metadata and the registered
// Origin95.Graph ProgID.  It runs before OleLoad, which is the first call that
// can activate the server named by the compound file.
HRESULT CheckOriginClass(IStorage* storage, REFCLSID requested, CLSID* rootOut) {
  CLSID root{};
  HRESULT hr = ReadRootClsid(storage, &root);
  if (FAILED(hr)) {
    return hr;
  }
  CLSID registered{};
  hr = CLSIDFromProgID(kOriginProgId, &registered);
  if (FAILED(hr)) {
    LogHr(L"CLSIDFromProgID(Origin95.Graph) is not registered", hr);
    return hr;
  }
  if (!IsEqualGuid(root, requested) || !IsEqualGuid(registered, requested)) {
    Log(L"Origin class gate rejected the storage: root=" + GuidText(root) +
        L", requested=" + GuidText(requested) +
        L", registered=" + GuidText(registered));
    return CLASS_E_CLASSNOTAVAILABLE;
  }
  if (rootOut) {
    *rootOut = root;
  }
  return S_OK;
}

class OriginHost final : public IOleClientSite,
                         public IOleInPlaceSite,
                         public IOleInPlaceFrame,
                         public IAdviseSink {
 public:
  OriginHost(HWND owner, HWND status, IStorage* storage, std::wstring outputBasePath = L"")
      : refCount_(1), owner_(owner), status_(status), storage_(storage),
        outputBasePath_(std::move(outputBasePath)) {
    if (storage_) {
      storage_->AddRef();
    }
  }

  OriginHost(const OriginHost&) = delete;
  OriginHost& operator=(const OriginHost&) = delete;

  ~OriginHost() {
    ReleaseObject();
    if (storage_) {
      storage_->Release();
      storage_ = nullptr;
    }
  }

  HRESULT LoadObject() {
    if (!storage_) {
      return E_UNEXPECTED;
    }
    if (object_) {
      return S_FALSE;
    }
    HRESULT hr = OleLoad(storage_, IID_IOleObject,
                         static_cast<IOleClientSite*>(this),
                         reinterpret_cast<void**>(&object_));
    if (FAILED(hr)) {
      LogHr(L"OleLoad", hr);
      return hr;
    }
    siteAttached_ = true;
    hr = object_->SetClientSite(static_cast<IOleClientSite*>(this));
    if (FAILED(hr)) {
      LogHr(L"IOleObject::SetClientSite", hr);
      ReleaseObject();
      return hr;
    }
    hr = object_->SetHostNames(L"SlideBridge", L"Origin95.Graph");
    if (FAILED(hr)) {
      LogHr(L"IOleObject::SetHostNames", hr);
      ReleaseObject();
      return hr;
    }
    hr = OleSetContainedObject(object_, TRUE);
    if (FAILED(hr)) {
      LogHr(L"OleSetContainedObject", hr);
      ReleaseObject();
      return hr;
    }
    IViewObject* view = nullptr;
    if (SUCCEEDED(object_->QueryInterface(IID_IViewObject, reinterpret_cast<void**>(&view)))) {
      view->SetAdvise(DVASPECT_CONTENT, 0, this);
      view->Release();
    }
    return S_OK;
  }

  HRESULT OpenInOrigin() {
    if (!object_) {
      return E_UNEXPECTED;
    }
    RECT rect{};
    if (owner_) {
      GetClientRect(owner_, &rect);
    }
    if (rect.right <= rect.left || rect.bottom <= rect.top) {
      rect.left = 0;
      rect.top = 0;
      rect.right = 800;
      rect.bottom = 600;
    }
    HRESULT hr = object_->DoVerb(OLEIVERB_OPEN, nullptr,
                                 static_cast<IOleClientSite*>(this), 0,
                                 owner_, &rect);
    if (FAILED(hr)) {
      LogHr(L"IOleObject::DoVerb(OLEIVERB_OPEN)", hr);
      return hr;
    }
    opened_ = true;
    SetStatus(L"Origin opened. Edit chart, save in Origin, then click 'Save and Close'.");
    const std::wstring sessionDir = GetDirectoryOf(outputBasePath_);
    if (!sessionDir.empty()) {
      Log(L"Origin opened for session: " + sessionDir);
      Log(L"Auto-export will capture preview.png upon Save.");
    }
    return S_OK;
  }

  HRESULT Run() {
    if (!object_) {
      return E_UNEXPECTED;
    }
    HRESULT hr = OleRun(object_);
    if (FAILED(hr)) {
      LogHr(L"OleRun", hr);
    }
    return hr;
  }

  // Drives Origin's internal expGraph command via COM Automation (Origin.ApplicationSI)
  // to export the active graph window as preview.png into the session folder.
  bool AutoExportOriginGraph(const std::wstring& sessionDir) {
    if (sessionDir.empty()) {
      return false;
    }
    CLSID clsid{};
    HRESULT hr = CLSIDFromProgID(L"Origin.ApplicationSI", &clsid);
    if (FAILED(hr)) {
      hr = CLSIDFromProgID(L"Origin.Application", &clsid);
    }
    if (FAILED(hr)) {
      LogHr(L"CLSIDFromProgID for Origin COM Automation", hr);
      return false;
    }

    IDispatch* pApp = nullptr;
    hr = CoCreateInstance(clsid, nullptr, CLSCTX_LOCAL_SERVER, IID_IDispatch,
                          reinterpret_cast<void**>(&pApp));
    if (FAILED(hr) || !pApp) {
      LogHr(L"CoCreateInstance(Origin COM Application)", hr);
      return false;
    }

    DISPID dispidExecute = 0;
    OLECHAR* memberName = const_cast<OLECHAR*>(L"Execute");
    hr = pApp->GetIDsOfNames(IID_NULL, &memberName, 1, LOCALE_USER_DEFAULT,
                             &dispidExecute);
    if (FAILED(hr)) {
      LogHr(L"GetIDsOfNames(Execute)", hr);
      pApp->Release();
      return false;
    }

    std::wstring labTalkCmd =
        L"expGraph type:=png filename:=\"preview\" path:=\"" + sessionDir +
        L"\" overwrite:=replace;";

    BSTR bstrCmd = SysAllocString(labTalkCmd.c_str());
    if (!bstrCmd) {
      pApp->Release();
      return false;
    }

    VARIANT arg;
    VariantInit(&arg);
    arg.vt = VT_BSTR;
    arg.bstrVal = bstrCmd;

    DISPPARAMS params{};
    params.rgvarg = &arg;
    params.cArgs = 1;
    params.cNamedArgs = 0;

    VARIANT varResult;
    VariantInit(&varResult);
    EXCEPINFO excepInfo{};
    UINT argErr = 0;

    hr = pApp->Invoke(dispidExecute, IID_NULL, LOCALE_USER_DEFAULT,
                      DISPATCH_METHOD, &params, &varResult, &excepInfo, &argErr);

    VariantClear(&arg);
    VariantClear(&varResult);
    pApp->Release();

    if (FAILED(hr)) {
      LogHr(L"Origin COM Execute(expGraph)", hr);
      return false;
    }

    std::wstring previewPng = sessionDir + L"\\preview.png";
    if (FileExists(previewPng)) {
      Log(L"Origin COM Auto-Export succeeded: " + previewPng);
      return true;
    } else {
      Log(L"Origin COM Execute returned S_OK, but preview.png was not found at: " + previewPng);
      return false;
    }
  }

  // A preview the user exported from Origin into the session folder.
  //
  // Origin keeps its live document in the "Contents" stream but does not
  // refresh the OLE presentation cache ("OlePres000/001") after an edit, and it
  // will not render live in OLEIVERB_OPEN mode either -- so our own render can
  // only ever show the chart as it looked before the change. Exporting from
  // Origin is the reliable route, and slidebridge prefers these filenames over
  // the ones we write.
  std::wstring ManualPreviewPath() const {
    const std::wstring directory = GetDirectoryOf(outputBasePath_);
    if (directory.empty()) {
      return std::wstring();
    }
    for (const wchar_t* name : {L"preview.png", L"preview.emf"}) {
      const std::wstring candidate = directory + L"\\" + name;
      if (FileExists(candidate)) {
        return candidate;
      }
    }
    return std::wstring();
  }

  // This is the one save path used by the UI and by IOleClientSite::SaveObject.
  // It mirrors OleSave's persistence sequence, but keeps SaveCompleted in a
  // finally-style path after IPersistStorage::Save has been entered.  The
  // guard prevents a server callback during Save from recursively entering
  // the same operation.
  HRESULT Save() {
    if (saving_) {
      return RPC_E_CALL_REJECTED;
    }
    if (persistencePoisoned_) {
      SetStatus(L"Persistence is unusable; restart this edit session.");
      return STG_E_REVERTED;
    }
    if (!object_ || !storage_) {
      return E_UNEXPECTED;
    }
    saving_ = true;
    IPersistStorage* persist = nullptr;
    HRESULT hr = object_->QueryInterface(IID_IPersistStorage,
                                         reinterpret_cast<void**>(&persist));
    if (SUCCEEDED(hr)) {
      CLSID clsid{};
      hr = RunPersistenceSave<HRESULT>(
          [](HRESULT result) { return SUCCEEDED(result); },
          [&] { return persist->GetClassID(&clsid); },
          [&] { return WriteClassStg(storage_, clsid); },
          [&] { return persist->Save(storage_, TRUE); },
          [&] { return storage_->Commit(STGC_DEFAULT); },
          [&] { return persist->SaveCompleted(nullptr); },
          persistencePoisoned_, [&](HRESULT completionHr) {
            LogHr(L"IPersistStorage::SaveCompleted (persistence unusable)",
                  completionHr);
          }, STG_E_REVERTED);
      persist->Release();
    }
    saving_ = false;
    if (SUCCEEDED(hr)) {
      explicitlySaved_ = true;
      std::wstring statusMsg = L"Saved to the output storage.";

      const std::wstring sessionDir = GetDirectoryOf(outputBasePath_);
      bool autoExported = false;
      if (!sessionDir.empty()) {
        autoExported = AutoExportOriginGraph(sessionDir);
      }

      if (!outputBasePath_.empty()) {
        std::wstring emfPath, pngPath;
        HRESULT exportHr = ExportPreview(outputBasePath_, &emfPath, &pngPath);
        if (SUCCEEDED(exportHr)) {
          std::wstring details;
          if (!emfPath.empty()) details += GetFilename(emfPath);
          if (!pngPath.empty()) {
            if (!details.empty()) details += L", ";
            details += GetFilename(pngPath);
          }
          statusMsg += L" Exported OLE previews: " + details;
        } else {
          statusMsg += L" (Warning: preview export failed)";
        }
      }

      if (autoExported) {
        statusMsg += L" Auto-exported Origin graph: preview.png";
      } else {
        const std::wstring manualPreview = ManualPreviewPath();
        if (!manualPreview.empty()) {
          statusMsg += L" Your exported preview will be used: " + GetFilename(manualPreview);
        }
      }

      Log(statusMsg);
      SetStatus(statusMsg);
      if (owner_) {
        InvalidateRect(owner_, nullptr, TRUE);
      }
    } else {
      LogHr(L"Save", hr);
      if (persistencePoisoned_) {
        SetStatus(L"SaveCompleted failed; persistence is unusable. Restart this edit session.");
      }
    }
    return hr;
  }

  void DrawPreview(HDC hdc, const RECT& targetRect) {
    if (!object_) {
      return;
    }
    SIZEL sizel{};
    HRESULT hr = object_->GetExtent(DVASPECT_CONTENT, &sizel);
    RECT drawRect = targetRect;
    if (SUCCEEDED(hr) && sizel.cx > 0 && sizel.cy > 0) {
      int availW = targetRect.right - targetRect.left;
      int availH = targetRect.bottom - targetRect.top;
      if (availW > 0 && availH > 0) {
        double extentAspect = static_cast<double>(sizel.cx) / static_cast<double>(sizel.cy);
        double targetAspect = static_cast<double>(availW) / static_cast<double>(availH);
        int drawW = availW;
        int drawH = availH;
        if (extentAspect > targetAspect) {
          drawH = static_cast<int>(availW / extentAspect);
        } else {
          drawW = static_cast<int>(availH * extentAspect);
        }
        drawRect.left = targetRect.left + (availW - drawW) / 2;
        drawRect.top = targetRect.top + (availH - drawH) / 2;
        drawRect.right = drawRect.left + drawW;
        drawRect.bottom = drawRect.top + drawH;
      }
    }

    HBRUSH whiteBrush = static_cast<HBRUSH>(GetStockObject(WHITE_BRUSH));
    FillRect(hdc, &drawRect, whiteBrush);

    OleDraw(object_, DVASPECT_CONTENT, hdc, &drawRect);

    HBRUSH frameBrush = CreateSolidBrush(RGB(180, 180, 180));
    FrameRect(hdc, &drawRect, frameBrush);
    DeleteObject(frameBrush);
  }

  HRESULT ExportPreview(const std::wstring& baseOutputPath,
                        std::wstring* emfOut = nullptr,
                        std::wstring* pngOut = nullptr) {
    if (!object_) {
      return E_UNEXPECTED;
    }
    std::wstring tempEmfPath = baseOutputPath + L".tmp.emf";
    std::wstring targetEmfPath = baseOutputPath + L".emf";
    std::wstring tempPngPath = baseOutputPath + L".tmp.png";
    std::wstring targetPngPath = baseOutputPath + L".png";

    bool emfSuccess = false;

    // Ask the server to refresh its cached presentation before we read it.
    // Origin keeps its real document in the "Contents" stream but does not
    // always rewrite the "OlePres000/001" presentation cache after an edit, so
    // GetData(CF_ENHMETAFILE) can hand back the chart as it looked *before* the
    // change. Update() is the documented nudge for that cache.
    object_->Update();

    SIZEL sizel{ 10000, 7500 };
    object_->GetExtent(DVASPECT_CONTENT, &sizel);
    if (sizel.cx <= 0) sizel.cx = 10000;
    if (sizel.cy <= 0) sizel.cy = 7500;

    // 1. Prefer a live render: OleDraw asks the running server to draw its
    //    current document. The cached GetData(CF_ENHMETAFILE) below is only a
    //    fallback, because trusting it first is what produced stale previews.
    {
      RECT rcHimetric = { 0, 0, sizel.cx, sizel.cy };
      HDC hdcMeta = CreateEnhMetaFileW(nullptr, tempEmfPath.c_str(), &rcHimetric, L"SlideBridge\0Origin Graph\0\0");
      if (hdcMeta) {
        HDC screenDc = GetDC(nullptr);
        int dpiX = screenDc ? GetDeviceCaps(screenDc, LOGPIXELSX) : 96;
        int dpiY = screenDc ? GetDeviceCaps(screenDc, LOGPIXELSY) : 96;
        if (screenDc) ReleaseDC(nullptr, screenDc);
        int px = MulDiv(sizel.cx, dpiX, 2540);
        int py = MulDiv(sizel.cy, dpiY, 2540);
        RECT rcPixels = { 0, 0, px, py };
        HRESULT drawHr = OleDraw(object_, DVASPECT_CONTENT, hdcMeta, &rcPixels);
        HENHMETAFILE hemf = CloseEnhMetaFile(hdcMeta);
        if (hemf) {
          if (SUCCEEDED(drawHr)) {
            emfSuccess = true;
          }
          DeleteEnhMetaFile(hemf);
        }
      }
    }

    // 2. Fallback: the object's own cached presentation metafile.
    if (!emfSuccess) {
      Log(L"Note: live OleDraw failed; falling back to the cached presentation metafile.");
      IDataObject* dataObj = nullptr;
      if (SUCCEEDED(object_->QueryInterface(IID_IDataObject, reinterpret_cast<void**>(&dataObj)))) {
        FORMATETC fetc = { CF_ENHMETAFILE, nullptr, DVASPECT_CONTENT, -1, TYMED_ENHMF };
        STGMEDIUM medium = {};
        if (SUCCEEDED(dataObj->GetData(&fetc, &medium))) {
          if (medium.tymed == TYMED_ENHMF && medium.hEnhMetaFile) {
            HENHMETAFILE hCopy = CopyEnhMetaFileW(medium.hEnhMetaFile, tempEmfPath.c_str());
            if (hCopy) {
              DeleteEnhMetaFile(hCopy);
              emfSuccess = true;
            }
          }
          ReleaseStgMedium(&medium);
        }
        dataObj->Release();
      }
    }

    if (emfSuccess) {
      MoveFileExW(tempEmfPath.c_str(), targetEmfPath.c_str(),
                  MOVEFILE_REPLACE_EXISTING | MOVEFILE_COPY_ALLOWED);
      if (emfOut) *emfOut = targetEmfPath;
      Log(L"Exported EMF preview: " + targetEmfPath);
    } else {
      Log(L"Warning: Failed to export EMF preview.");
    }

    // 3. Export PNG via GDI+ at 300 DPI
    bool pngSuccess = false;
    int targetDpi = 300;
    int pngW = MulDiv(sizel.cx, targetDpi, 2540);
    int pngH = MulDiv(sizel.cy, targetDpi, 2540);
    if (pngW < 200) pngW = 200;
    if (pngH < 200) pngH = 200;
    if (pngW > 4096) {
      pngH = MulDiv(pngH, 4096, pngW);
      pngW = 4096;
    }
    if (pngH > 4096) {
      pngW = MulDiv(pngW, 4096, pngH);
      pngH = 4096;
    }

    if (emfSuccess) {
      Gdiplus::Metafile metafile(targetEmfPath.c_str());
      if (metafile.GetLastStatus() == Gdiplus::Ok) {
        Gdiplus::Bitmap bitmap(pngW, pngH, PixelFormat32bppARGB);
        Gdiplus::Graphics g(&bitmap);
        g.SetSmoothingMode(Gdiplus::SmoothingModeHighQuality);
        g.SetInterpolationMode(Gdiplus::InterpolationModeHighQualityBicubic);
        g.Clear(Gdiplus::Color(255, 255, 255, 255));
        g.DrawImage(&metafile, 0, 0, pngW, pngH);
        if (bitmap.Save(tempPngPath.c_str(), &kPngEncoderClsid, nullptr) == Gdiplus::Ok) {
          pngSuccess = true;
        }
      }
    }

    if (!pngSuccess) {
      BITMAPINFO bmi{};
      bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
      bmi.bmiHeader.biWidth = pngW;
      bmi.bmiHeader.biHeight = -pngH;
      bmi.bmiHeader.biPlanes = 1;
      bmi.bmiHeader.biBitCount = 32;
      bmi.bmiHeader.biCompression = BI_RGB;
      void* bits = nullptr;
      HDC screenDc = GetDC(nullptr);
      HDC memDc = CreateCompatibleDC(screenDc);
      HBITMAP hBmp = CreateDIBSection(screenDc, &bmi, DIB_RGB_COLORS, &bits, nullptr, 0);
      if (screenDc) ReleaseDC(nullptr, screenDc);
      if (memDc && hBmp) {
        HGDIOBJ oldBmp = SelectObject(memDc, hBmp);
        RECT rc = { 0, 0, pngW, pngH };
        HBRUSH whiteBrush = static_cast<HBRUSH>(GetStockObject(WHITE_BRUSH));
        FillRect(memDc, &rc, whiteBrush);
        OleDraw(object_, DVASPECT_CONTENT, memDc, &rc);
        SelectObject(memDc, oldBmp);

        Gdiplus::Bitmap bitmap(hBmp, nullptr);
        if (bitmap.Save(tempPngPath.c_str(), &kPngEncoderClsid, nullptr) == Gdiplus::Ok) {
          pngSuccess = true;
        }
      }
      if (hBmp) DeleteObject(hBmp);
      if (memDc) DeleteDC(memDc);
    }

    if (pngSuccess) {
      MoveFileExW(tempPngPath.c_str(), targetPngPath.c_str(),
                  MOVEFILE_REPLACE_EXISTING | MOVEFILE_COPY_ALLOWED);
      if (pngOut) *pngOut = targetPngPath;
      Log(L"Exported PNG preview: " + targetPngPath);
    } else {
      Log(L"Warning: Failed to export PNG preview.");
    }

    return (emfSuccess || pngSuccess) ? S_OK : S_FALSE;
  }

  HRESULT CloseAfterSave() {
    if (!object_) {
      return S_FALSE;
    }
    if (!explicitlySaved_) {
      return E_ACCESSDENIED;
    }
    HRESULT hr = object_->Close(OLECLOSE_NOSAVE);
    if (FAILED(hr)) {
      LogHr(L"IOleObject::Close(OLECLOSE_NOSAVE)", hr);
      return hr;
    }
    closed_ = true;
    SetStatus(L"Origin closed after a successful save.");
    return S_OK;
  }

  // This is an explicit discard escape hatch for a poisoned persistence
  // lifecycle.  The caller must obtain a deliberate user confirmation before
  // invoking it; the input storage is never opened for writing.
  HRESULT DiscardAfterPersistenceFailure() {
    if (!object_) {
      return S_FALSE;
    }
    if (!persistencePoisoned_) {
      return E_ACCESSDENIED;
    }
    HRESULT hr = object_->Close(OLECLOSE_NOSAVE);
    if (FAILED(hr)) {
      LogHr(L"IOleObject::Close(OLECLOSE_NOSAVE) after discard", hr);
      return hr;
    }
    closed_ = true;
    SetStatus(L"Discarded unsaved changes; the input remains unchanged.");
    return S_OK;
  }

  bool HasObject() const { return object_ != nullptr; }
  bool IsClosed() const { return closed_; }
  bool PersistencePoisoned() const { return persistencePoisoned_; }

  void ReleaseObject() {
    if (!object_) {
      return;
    }
    // Never issue OLECLOSE_NOSAVE here: callers must first complete an
    // explicit successful save through Save().  Detaching the site breaks the
    // object -> client-site reference before releasing our object reference.
    if (siteAttached_) {
      IViewObject* view = nullptr;
      if (SUCCEEDED(object_->QueryInterface(IID_IViewObject, reinterpret_cast<void**>(&view)))) {
        view->SetAdvise(DVASPECT_CONTENT, 0, nullptr);
        view->Release();
      }
      object_->SetClientSite(nullptr);
      siteAttached_ = false;
    }
    object_->Release();
    object_ = nullptr;
    closed_ = true;
  }

  void SetStatus(const std::wstring& message) {
    Log(message);
    if (status_) {
      SetWindowTextW(status_, message.c_str());
    }
  }

  // IUnknown
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** object) override {
    if (!object) {
      return E_POINTER;
    }
    *object = nullptr;
    if (riid == IID_IUnknown || riid == IID_IOleClientSite) {
      *object = static_cast<IOleClientSite*>(this);
    } else if (riid == IID_IOleInPlaceSite || riid == IID_IOleWindow) {
      *object = static_cast<IOleInPlaceSite*>(this);
    } else if (riid == IID_IOleInPlaceFrame) {
      *object = static_cast<IOleInPlaceFrame*>(this);
    } else if (riid == IID_IAdviseSink) {
      *object = static_cast<IAdviseSink*>(this);
    } else {
      return E_NOINTERFACE;
    }
    AddRef();
    return S_OK;
  }

  ULONG STDMETHODCALLTYPE AddRef() override {
    return static_cast<ULONG>(InterlockedIncrement(&refCount_));
  }

  ULONG STDMETHODCALLTYPE Release() override {
    ULONG count = static_cast<ULONG>(InterlockedDecrement(&refCount_));
    if (count == 0) {
      delete this;
    }
    return count;
  }

  // IOleClientSite
  HRESULT STDMETHODCALLTYPE SaveObject() override { return Save(); }

  HRESULT STDMETHODCALLTYPE GetMoniker(DWORD, DWORD, IMoniker**) override {
    return E_NOTIMPL;
  }

  HRESULT STDMETHODCALLTYPE GetContainer(IOleContainer** container) override {
    if (container) {
      *container = nullptr;
    }
    return E_NOINTERFACE;
  }

  HRESULT STDMETHODCALLTYPE ShowObject() override { return S_OK; }

  HRESULT STDMETHODCALLTYPE OnShowWindow(BOOL show) override {
    SetStatus(show ? L"Origin server window shown. Save explicitly to commit."
                    : L"Origin server window hidden. The file remains open.");
    return S_OK;
  }

  HRESULT STDMETHODCALLTYPE RequestNewObjectLayout() override { return E_NOTIMPL; }

  // IOleWindow / IOleInPlaceSite
  HRESULT STDMETHODCALLTYPE GetWindow(HWND* window) override {
    if (!window) {
      return E_POINTER;
    }
    *window = owner_;
    return owner_ ? S_OK : E_FAIL;
  }

  HRESULT STDMETHODCALLTYPE ContextSensitiveHelp(BOOL) override { return E_NOTIMPL; }
  HRESULT STDMETHODCALLTYPE CanInPlaceActivate() override { return S_OK; }
  HRESULT STDMETHODCALLTYPE OnInPlaceActivate() override { return S_OK; }
  HRESULT STDMETHODCALLTYPE OnUIActivate() override { return S_OK; }

  HRESULT STDMETHODCALLTYPE GetWindowContext(
      IOleInPlaceFrame** frame, IOleInPlaceUIWindow** docWindow,
      LPRECT posRect, LPRECT clipRect,
      LPOLEINPLACEFRAMEINFO frameInfo) override {
    if (!frame || !docWindow || !posRect || !clipRect || !frameInfo) {
      return E_POINTER;
    }
    *frame = static_cast<IOleInPlaceFrame*>(this);
    (*frame)->AddRef();
    *docWindow = nullptr;
    RECT rect{};
    if (owner_) {
      GetClientRect(owner_, &rect);
    }
    if (rect.right <= rect.left || rect.bottom <= rect.top) {
      rect.right = 800;
      rect.bottom = 600;
    }
    *posRect = rect;
    *clipRect = rect;
    frameInfo->cb = sizeof(*frameInfo);
    frameInfo->fMDIApp = FALSE;
    frameInfo->hwndFrame = owner_;
    frameInfo->haccel = nullptr;
    frameInfo->cAccelEntries = 0;
    return S_OK;
  }

  HRESULT STDMETHODCALLTYPE Scroll(SIZE) override { return E_NOTIMPL; }
  HRESULT STDMETHODCALLTYPE OnUIDeactivate(BOOL) override { return S_OK; }
  HRESULT STDMETHODCALLTYPE OnInPlaceDeactivate() override { return S_OK; }
  HRESULT STDMETHODCALLTYPE DiscardUndoState() override { return E_NOTIMPL; }
  HRESULT STDMETHODCALLTYPE DeactivateAndUndo() override { return E_NOTIMPL; }
  HRESULT STDMETHODCALLTYPE OnPosRectChange(LPCRECT rect) override {
    if (!object_ || !rect) {
      return E_INVALIDARG;
    }
    IOleInPlaceObject* inPlace = nullptr;
    HRESULT hr = object_->QueryInterface(IID_IOleInPlaceObject,
                                         reinterpret_cast<void**>(&inPlace));
    if (SUCCEEDED(hr)) {
      hr = inPlace->SetObjectRects(rect, rect);
      inPlace->Release();
    }
    return hr;
  }

  // IOleInPlaceFrame
  HRESULT STDMETHODCALLTYPE GetBorder(LPRECT border) override {
    if (!border || !owner_) {
      return E_INVALIDARG;
    }
    GetClientRect(owner_, border);
    return S_OK;
  }

  HRESULT STDMETHODCALLTYPE RequestBorderSpace(LPCBORDERWIDTHS) override { return INPLACE_E_NOTOOLSPACE; }
  HRESULT STDMETHODCALLTYPE SetBorderSpace(LPCBORDERWIDTHS) override { return S_OK; }
  HRESULT STDMETHODCALLTYPE SetActiveObject(IOleInPlaceActiveObject*, LPCOLESTR) override { return S_OK; }
  HRESULT STDMETHODCALLTYPE InsertMenus(HMENU, LPOLEMENUGROUPWIDTHS) override { return E_NOTIMPL; }
  HRESULT STDMETHODCALLTYPE SetMenu(HMENU, HOLEMENU, HWND) override { return S_OK; }
  HRESULT STDMETHODCALLTYPE RemoveMenus(HMENU) override { return S_OK; }
  HRESULT STDMETHODCALLTYPE SetStatusText(LPCOLESTR text) override {
    if (text) {
      SetStatus(text);
    }
    return S_OK;
  }
  HRESULT STDMETHODCALLTYPE EnableModeless(BOOL) override { return S_OK; }
  HRESULT STDMETHODCALLTYPE TranslateAccelerator(LPMSG, WORD) override { return E_NOTIMPL; }

  // IAdviseSink
  void STDMETHODCALLTYPE OnDataChange(FORMATETC*, STGMEDIUM*) override {}
  void STDMETHODCALLTYPE OnViewChange(DWORD, LONG) override {
    if (owner_) {
      InvalidateRect(owner_, nullptr, FALSE);
    }
  }
  void STDMETHODCALLTYPE OnRename(IMoniker*) override {}
  void STDMETHODCALLTYPE OnSave() override {
    if (owner_) {
      InvalidateRect(owner_, nullptr, FALSE);
    }
  }
  void STDMETHODCALLTYPE OnClose() override {}

 private:
  LONG refCount_;
  HWND owner_;
  HWND status_;
  IStorage* storage_ = nullptr;
  IOleObject* object_ = nullptr;
  bool siteAttached_ = false;
  bool opened_ = false;
  bool explicitlySaved_ = false;
  bool closed_ = false;
  bool saving_ = false;
  bool persistencePoisoned_ = false;
  std::wstring outputBasePath_;
};

class EditApp final {
 public:
  EditApp(std::wstring output, IStorage* storage)
      : output_(std::move(output)), storage_(storage) {
    if (storage_) {
      storage_->AddRef();
    }
  }

  EditApp(const EditApp&) = delete;
  EditApp& operator=(const EditApp&) = delete;

  ~EditApp() {
    if (host_) {
      host_->ReleaseObject();
      host_->Release();
      host_ = nullptr;
    }
    if (storage_) {
      storage_->Release();
      storage_ = nullptr;
    }
  }

  HRESULT CreateAndShow() {
    WNDCLASSW wc{};
    wc.lpfnWndProc = &EditApp::WindowProc;
    wc.hInstance = GetModuleHandleW(nullptr);
    wc.lpszClassName = kWindowClass;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1);
    RegisterClassW(&wc);

    RECT desired{0, 0, 1024, 768};
    AdjustWindowRect(&desired, WS_OVERLAPPEDWINDOW, FALSE);
    window_ = CreateWindowExW(0, kWindowClass, kWindowTitle,
                              WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                              CW_USEDEFAULT, CW_USEDEFAULT,
                              desired.right - desired.left,
                              desired.bottom - desired.top,
                              nullptr, nullptr, wc.hInstance, this);
    if (!window_) {
      HRESULT hr = HRESULT_FROM_WIN32(GetLastError());
      LogHr(L"CreateWindowExW", hr);
      return hr;
    }
    ShowWindow(window_, SW_SHOW);
    UpdateWindow(window_);

    MSG message{};
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
      TranslateMessage(&message);
      DispatchMessageW(&message);
    }
    return exitCode_;
  }

 private:
  static LRESULT CALLBACK WindowProc(HWND window, UINT message,
                                     WPARAM wParam, LPARAM lParam) {
    EditApp* app = reinterpret_cast<EditApp*>(GetWindowLongPtrW(window, GWLP_USERDATA));
    if (message == WM_NCCREATE) {
      auto* create = reinterpret_cast<CREATESTRUCTW*>(lParam);
      app = static_cast<EditApp*>(create->lpCreateParams);
      SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(app));
      app->window_ = window;
    }
    if (!app) {
      return DefWindowProcW(window, message, wParam, lParam);
    }
    return app->HandleMessage(message, wParam, lParam);
  }

  LRESULT HandleMessage(UINT message, WPARAM wParam, LPARAM lParam) {
    switch (message) {
      case WM_CREATE:
        CreateControls();
        host_ = new OriginHost(window_, status_, storage_, GetBasePathWithoutExt(output_));
        return 0;

      case WM_PAINT: {
        PAINTSTRUCT ps{};
        HDC hdc = BeginPaint(window_, &ps);
        RECT client{};
        GetClientRect(window_, &client);
        RECT previewBox{ 16, 96, client.right - 16, client.bottom - 16 };
        if (previewBox.right > previewBox.left && previewBox.bottom > previewBox.top) {
          HBRUSH bgBrush = CreateSolidBrush(RGB(245, 245, 245));
          FillRect(hdc, &previewBox, bgBrush);
          DeleteObject(bgBrush);

          HBRUSH borderBrush = CreateSolidBrush(RGB(200, 200, 200));
          FrameRect(hdc, &previewBox, borderBrush);
          DeleteObject(borderBrush);

          if (host_ && host_->HasObject()) {
            RECT innerBox{ previewBox.left + 8, previewBox.top + 8,
                           previewBox.right - 8, previewBox.bottom - 8 };
            host_->DrawPreview(hdc, innerBox);
          } else {
            SetBkMode(hdc, TRANSPARENT);
            SetTextColor(hdc, RGB(128, 128, 128));
            DrawTextW(hdc, L"Origin chart preview will appear here...", -1,
                      &previewBox, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
          }
        }
        EndPaint(window_, &ps);
        return 0;
      }

      case WM_SIZE:
        InvalidateRect(window_, nullptr, TRUE);
        return 0;

      case WM_SHOWWINDOW:
        if (wParam && !openAttempted_) {
          openAttempted_ = true;
          HRESULT hr = host_->LoadObject();
          if (SUCCEEDED(hr)) {
            hr = host_->OpenInOrigin();
          }
          if (FAILED(hr)) {
            exitCode_ = hr;
            SetStatus(L"Unable to open the Origin object. Close this window.");
          }
        }
        return 0;

      case WM_COMMAND:
        // Automation may send WM_COMMAND synchronously from another process.
        // COM callouts in that input-sync context fail with RPC_E_CANTCALLOUT_ININPUTSYNCCALL.
        // Execute OLE work on our own posted-message turn instead.
        if (HIWORD(wParam) == BN_CLICKED) {
          PostMessageW(window_, WM_APP + 1, wParam, 0);
        }
        return 0;

      case WM_APP + 1:
        if (HIWORD(wParam) == BN_CLICKED) {
          switch (LOWORD(wParam)) {
            case kOpenButton:
              if (host_) {
                host_->OpenInOrigin();
              }
              return 0;
            case kSaveButton:
              SaveObject();
              return 0;
            case kSaveCloseButton:
              if (SaveObject()) {
                CloseWindowAfterSave();
              }
              return 0;
            case kDiscardCloseButton:
              DiscardAndClose();
              return 0;
            default:
              break;
          }
        }
        break;

      case WM_CLOSE:
        PostMessageW(window_, WM_APP + 1, kSaveCloseButton, 0);
        return 0;

      case WM_DESTROY:
        PostQuitMessage(exitCode_ == S_OK ? 0 : static_cast<int>(exitCode_));
        return 0;

      default:
        break;
    }
    return DefWindowProcW(window_, message, wParam, lParam);
  }

  void CreateControls() {
    CreateWindowW(L"BUTTON", L"Open in Origin", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                  16, 16, 150, 32, window_,
                  reinterpret_cast<HMENU>(static_cast<INT_PTR>(kOpenButton)),
                  GetModuleHandleW(nullptr), nullptr);
    CreateWindowW(L"BUTTON", L"Save", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                  176, 16, 100, 32, window_,
                  reinterpret_cast<HMENU>(static_cast<INT_PTR>(kSaveButton)),
                  GetModuleHandleW(nullptr), nullptr);
    CreateWindowW(L"BUTTON", L"Save and Close", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                  286, 16, 140, 32, window_,
                  reinterpret_cast<HMENU>(static_cast<INT_PTR>(kSaveCloseButton)),
                  GetModuleHandleW(nullptr), nullptr);
    discardButton_ = CreateWindowW(
        L"BUTTON", L"Discard and Close", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
        436, 16, 150, 32, window_,
        reinterpret_cast<HMENU>(static_cast<INT_PTR>(kDiscardCloseButton)),
        GetModuleHandleW(nullptr), nullptr);
    EnableWindow(discardButton_, FALSE);
    status_ = CreateWindowW(L"STATIC", L"Loading...", WS_CHILD | WS_VISIBLE,
                            16, 60, 980, 28, window_,
                            reinterpret_cast<HMENU>(static_cast<INT_PTR>(kStatusControl)),
                            GetModuleHandleW(nullptr), nullptr);
  }

  void SetStatus(const std::wstring& status) {
    Log(status);
    if (status_) {
      SetWindowTextW(status_, status.c_str());
    }
  }

  bool SaveObject() {
    if (!host_ || !host_->HasObject()) {
      SetStatus(L"No Origin object is loaded.");
      return true;
    }
    HRESULT hr = host_->Save();
    if (FAILED(hr)) {
      if (host_->PersistencePoisoned()) {
        EnableWindow(discardButton_, TRUE);
        SetStatus(L"Persistence is unusable; confirm Discard and Close to abandon this output copy.");
      } else {
        SetStatus(L"Save failed; the window remains open.");
      }
      return false;
    }
    return true;
  }

  void CloseWindowAfterSave() {
    if (!host_) {
      DestroyWindow(window_);
      return;
    }
    HRESULT hr = host_->CloseAfterSave();
    if (FAILED(hr)) {
      SetStatus(L"Origin did not close after saving; the window remains open.");
      return;
    }
    DestroyWindow(window_);
  }

  void DiscardAndClose() {
    if (!host_ || !host_->HasObject()) {
      DestroyWindow(window_);
      return;
    }
    if (!host_->PersistencePoisoned()) {
      SetStatus(L"Discard is available only after a failed SaveCompleted lifecycle.");
      return;
    }
    int answer = MessageBoxW(
        window_,
        L"Discard unsaved changes and close? Only the disposable output copy will be abandoned; the input remains unchanged.",
        L"Confirm discard", MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2);
    if (answer != IDYES) {
      return;
    }
    HRESULT hr = host_->DiscardAfterPersistenceFailure();
    if (FAILED(hr)) {
      SetStatus(L"Discard failed; the window remains open.");
      return;
    }
    DestroyWindow(window_);
  }

  std::wstring output_;
  IStorage* storage_ = nullptr;
  HWND window_ = nullptr;
  HWND status_ = nullptr;
  HWND discardButton_ = nullptr;
  OriginHost* host_ = nullptr;
  HRESULT exitCode_ = S_OK;
  bool openAttempted_ = false;
};

HRESULT RunProbe(const std::wstring& input, const std::wstring& output,
                REFCLSID requested) {
  HRESULT hr = CopyInputToOutput(input, output);
  if (FAILED(hr)) {
    return hr;
  }
  IStorage* storage = nullptr;
  hr = OpenStorage(output, STGM_READWRITE | STGM_SHARE_EXCLUSIVE, &storage);
  if (FAILED(hr)) {
    LogHr(L"StgOpenStorage(output)", hr);
    return hr;
  }
  hr = CheckOriginClass(storage, requested, nullptr);
  if (FAILED(hr)) {
    storage->Release();
    return hr;
  }
  Log(L"probe: LOAD");
  auto* host = new OriginHost(nullptr, nullptr, storage, GetBasePathWithoutExt(output));
  storage->Release();
  hr = host->LoadObject();
  if (SUCCEEDED(hr)) {
    Log(L"probe: OleRun");
    hr = host->Run();
  }
  if (SUCCEEDED(hr)) {
    Log(L"probe: Save");
    hr = host->Save();
  }
  if (SUCCEEDED(hr)) {
    Log(L"probe: Close");
    hr = host->CloseAfterSave();
  }
  host->ReleaseObject();
  host->Release();
  if (FAILED(hr)) {
    return hr;
  }

  Log(L"probe: storage roundtrip (LOAD -> OleRun -> Save -> Close -> reload -> Close)");
  storage = nullptr;
  hr = OpenStorage(output, STGM_READWRITE | STGM_SHARE_EXCLUSIVE, &storage);
  if (FAILED(hr)) {
    LogHr(L"StgOpenStorage(reload output)", hr);
    return hr;
  }
  hr = CheckOriginClass(storage, requested, nullptr);
  if (SUCCEEDED(hr)) {
    auto* reloaded = new OriginHost(nullptr, nullptr, storage);
    storage->Release();
    storage = nullptr;
    hr = reloaded->LoadObject();
    if (SUCCEEDED(hr)) {
      // The first lifecycle has already saved.  This second object is only a
      // load/close roundtrip check and is deliberately not called an edit or
      // visual verification.
      reloaded->SetStatus(L"probe: reloaded output; saving and closing roundtrip object");
      hr = reloaded->Save();
      if (SUCCEEDED(hr)) {
        hr = reloaded->CloseAfterSave();
      }
    }
    reloaded->ReleaseObject();
    reloaded->Release();
  }
  if (storage) {
    storage->Release();
  }
  if (SUCCEEDED(hr)) {
    Log(L"probe: storage roundtrip complete; edit/visual verification not claimed");
  } else {
    LogHr(L"probe reload", hr);
  }
  return hr;
}

HRESULT RunInspect(const std::wstring& input) {
  IStorage* storage = nullptr;
  HRESULT hr = OpenStorage(input, STGM_READ | STGM_SHARE_DENY_WRITE, &storage);
  if (FAILED(hr)) {
    LogHr(L"StgOpenStorage(inspect)", hr);
    return hr;
  }
  CLSID clsid{};
  hr = ReadRootClsid(storage, &clsid);
  storage->Release();
  if (SUCCEEDED(hr)) {
    Log(L"inspect: root CLSID=" + GuidText(clsid) + L" (read-only; no activation)");
  } else {
    LogHr(L"IStorage::Stat", hr);
  }
  return hr;
}

HRESULT RunEdit(const std::wstring& input, const std::wstring& output,
                REFCLSID requested) {
  HRESULT hr = CopyInputToOutput(input, output);
  if (FAILED(hr)) {
    return hr;
  }
  IStorage* storage = nullptr;
  hr = OpenStorage(output, STGM_READWRITE | STGM_SHARE_EXCLUSIVE, &storage);
  if (FAILED(hr)) {
    LogHr(L"StgOpenStorage(output)", hr);
    return hr;
  }
  hr = CheckOriginClass(storage, requested, nullptr);
  if (FAILED(hr)) {
    storage->Release();
    return hr;
  }
  Log(L"edit: class gate passed; opening native Origin host window");
  EditApp app(output, storage);
  storage->Release();
  return app.CreateAndShow();
}

void PrintUsage() {
  Log(L"Usage:");
  Log(L"  origin-bridge.exe inspect INPUT.bin");
  Log(L"  origin-bridge.exe edit INPUT.bin OUTPUT.bin --clsid {GUID}");
  Log(L"  origin-bridge.exe --probe INPUT.bin OUTPUT.bin --clsid {GUID}");
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
  if (argc < 2) {
    PrintUsage();
    return 2;
  }

  Gdiplus::GdiplusStartupInput gdiplusStartupInput;
  ULONG_PTR gdiplusToken = 0;
  Gdiplus::Status gdiStatus = Gdiplus::GdiplusStartup(&gdiplusToken, &gdiplusStartupInput, nullptr);

  HRESULT hr = OleInitialize(nullptr);
  if (FAILED(hr)) {
    LogHr(L"OleInitialize", hr);
    if (gdiStatus == Gdiplus::Ok) {
      Gdiplus::GdiplusShutdown(gdiplusToken);
    }
    return 1;
  }

  std::wstring command = argv[1];
  if (command == L"inspect" && argc == 3) {
    hr = RunInspect(argv[2]);
  } else if ((command == L"edit" || command == L"--probe") && argc == 6 &&
             std::wstring(argv[4]) == L"--clsid") {
    CLSID requested{};
    hr = ParseClsid(argv[5], &requested);
    if (SUCCEEDED(hr)) {
      if (command == L"edit") {
        hr = RunEdit(argv[2], argv[3], requested);
      } else {
        hr = RunProbe(argv[2], argv[3], requested);
      }
    } else {
      LogHr(L"CLSIDFromString", hr);
    }
  } else {
    PrintUsage();
    hr = E_INVALIDARG;
  }

  OleUninitialize();
  if (gdiStatus == Gdiplus::Ok) {
    Gdiplus::GdiplusShutdown(gdiplusToken);
  }
  return SUCCEEDED(hr) ? 0 : 1;
}
