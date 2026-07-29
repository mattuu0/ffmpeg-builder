// Minimal WASAPI loopback capture: streams the default audio-render device's
// output (system/app audio) as raw interleaved float32 PCM to stdout.
//
// Superseded by the native "wasapi" avdevice indev (patches/wasapi-indev.patch,
// libavdevice/wasapi.c) -- ffmpeg -f wasapi -i default now does the same
// thing directly, without a separate process/pipe. This standalone tool is
// no longer built or shipped by docker/windows/Dockerfile; the source is
// kept only for reference / for anyone who still wants the process+pipe
// approach.
//
// Usage: wasapi_loopback.exe > out.pcm
//   or piped straight into ffmpeg:
//   wasapi_loopback.exe | ffmpeg -f f32le -ar <rate> -ac <channels> -i pipe:0 ...
//
// The actual sample rate / channel count depend on the current default
// device's mix format and are NOT known ahead of time, so this tool prints
// them to stderr as "RATE=<n> CHANNELS=<n>" on startup. A wrapper script
// should read that line before invoking ffmpeg, or ffmpeg's rate/channels
// flags should be set to match the known device format in advance.
#include <audioclient.h>
#include <cstdio>
#include <fcntl.h>
#include <io.h>
#include <mmdeviceapi.h>
#include <windows.h>

#define EXIT_ON_FAIL(hr, msg)                                                \
  if (FAILED(hr)) {                                                         \
    fprintf(stderr, "FATAL: %s (hr=0x%08lx)\n", msg, (unsigned long)(hr));   \
    return 1;                                                               \
  }

int main() {
  HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
  EXIT_ON_FAIL(hr, "CoInitializeEx failed");

  IMMDeviceEnumerator *enumerator = nullptr;
  hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
                        __uuidof(IMMDeviceEnumerator), (void **)&enumerator);
  EXIT_ON_FAIL(hr, "CoCreateInstance(MMDeviceEnumerator) failed");

  IMMDevice *device = nullptr;
  hr = enumerator->GetDefaultAudioEndpoint(eRender, eConsole, &device);
  EXIT_ON_FAIL(hr, "GetDefaultAudioEndpoint failed");

  IAudioClient *audioClient = nullptr;
  hr = device->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr,
                        (void **)&audioClient);
  EXIT_ON_FAIL(hr, "IMMDevice::Activate failed");

  WAVEFORMATEX *mixFormat = nullptr;
  hr = audioClient->GetMixFormat(&mixFormat);
  EXIT_ON_FAIL(hr, "GetMixFormat failed");

  const REFERENCE_TIME bufferDuration = 20 * 10000; // 20ms in 100ns units
  hr = audioClient->Initialize(AUDCLNT_SHAREMODE_SHARED,
                               AUDCLNT_STREAMFLAGS_LOOPBACK, bufferDuration,
                               0, mixFormat, nullptr);
  EXIT_ON_FAIL(hr, "IAudioClient::Initialize failed");

  IAudioCaptureClient *captureClient = nullptr;
  hr = audioClient->GetService(__uuidof(IAudioCaptureClient),
                               (void **)&captureClient);
  EXIT_ON_FAIL(hr, "GetService(IAudioCaptureClient) failed");

  fprintf(stderr, "RATE=%lu CHANNELS=%u BITS=%u\n",
          (unsigned long)mixFormat->nSamplesPerSec, mixFormat->nChannels,
          mixFormat->wBitsPerSample);
  fflush(stderr);

  _setmode(_fileno(stdout), _O_BINARY);

  hr = audioClient->Start();
  EXIT_ON_FAIL(hr, "IAudioClient::Start failed");

  const DWORD frameBytes = mixFormat->nBlockAlign;

  for (;;) {
    Sleep(10);

    UINT32 packetLength = 0;
    hr = captureClient->GetNextPacketSize(&packetLength);
    if (FAILED(hr))
      break;

    while (packetLength != 0) {
      BYTE *data = nullptr;
      UINT32 numFrames = 0;
      DWORD flags = 0;
      hr = captureClient->GetBuffer(&data, &numFrames, &flags, nullptr,
                                    nullptr);
      if (FAILED(hr))
        break;

      if (numFrames != 0) {
        if (!(flags & AUDCLNT_BUFFERFLAGS_SILENT)) {
          fwrite(data, frameBytes, numFrames, stdout);
        } else {
          // Write explicit silence so the output stream stays in sync with
          // wall-clock time even when the render device has nothing playing.
          static BYTE zero[4096] = {0};
          UINT32 remaining = numFrames;
          while (remaining) {
            UINT32 chunk = remaining;
            UINT32 maxFrames = sizeof(zero) / (frameBytes ? frameBytes : 1);
            if (chunk > maxFrames)
              chunk = maxFrames;
            fwrite(zero, frameBytes, chunk, stdout);
            remaining -= chunk;
          }
        }
      }

      hr = captureClient->ReleaseBuffer(numFrames);
      if (FAILED(hr))
        break;

      hr = captureClient->GetNextPacketSize(&packetLength);
      if (FAILED(hr))
        break;
    }
    fflush(stdout);
  }

  audioClient->Stop();
  CoTaskMemFree(mixFormat);
  captureClient->Release();
  audioClient->Release();
  device->Release();
  enumerator->Release();
  CoUninitialize();
  return 0;
}
