# whisper.cpp's speech server. There is no official arm64 image, so it is built here,
# for the Pi 5's Cortex-A76 rather than for whatever machine runs the build.
FROM debian:trixie-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake git ca-certificates
RUN git clone --depth 1 --branch v1.9.5 https://github.com/ggml-org/whisper.cpp /src \
 && cmake -S /src -B /build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
      -DGGML_NATIVE=OFF -DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod+fp16 \
 && cmake --build /build -j --target whisper-server

FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY --from=build /build/bin/whisper-server /usr/local/bin/
ENTRYPOINT ["whisper-server"]
