# 🎬 Ultimate Synology Media & *Arr Automation Stack (`mediarr-stack`)

시놀로지 NAS(**DS920+** 및 DSM 7.2 전 모델)와 모든 홈서버 환경을 위해 **단일 프로젝트(`mediarr-stack`)와 단일 `docker-compose.yml` 안에서 전용 관제 도커 이미지(`kimmingil/mediarr-stack:latest`)와 14대 미디어·*Arr 서버가 100% 유기적으로 연동·관리되는 현존 최고 수준의 올인원 미디어 자동화 생태계**입니다.

> **핵심 설계 원칙:**
> - **기존 `plexhw` & `qbittorrent_gluetun` 100% 무손실 승계:** 기존에 사용하시던 `/volume1/docker/plexhw`(6.7GB 메타데이터·설정), qBittorrent 포트(`8181`), Surfshark Tokyo WireGuard/OpenVPN 설정, `/volume1/video` 및 `/volume1/torrents` 경로를 그대로 유지하면서 단일 프로젝트로 완벽 통합했습니다.
> - **기존 Watchtower 100% 완벽 연동 (중복 컨테이너 제외 + 전용 라벨 탑재):** 시놀로지 NAS에서 이미 구동 중인 Watchtower와 충돌하지 않도록 중복 Watchtower 컨테이너는 넣지 않고, 15개 전 컨테이너에 `com.centurylinklabs.watchtower.enable=true` 라벨과 VPN 종속성 라벨(`com.centurylinklabs.watchtower.depends-on=mediarr-gluetun`)을 탑재하여 기존 Watchtower가 VPN 끊김 없이 안전하게 자동 업데이트합니다.
> - **내장 24시간 주기 자동 DB 닥터:** 별도의 작업 스케줄러 등록 없이도 `mediarr-control-center`가 24시간마다 자동으로 좀비 PID 청소, SQLite DB 최적화(`VACUUM`), 설정 백업을 수행합니다.
> - **TRaSH Guides 0.1초 하드링크 표준:** 전 컨테이너가 `/volume1/mediarr:/data:rw` 단일 볼륨을 공유하여, 수십 GB의 4K 영화도 다운로드 완료 즉시 **복사 시간 0.1초, 추가 디스크 소모 0바이트(하드링크)**로 Plex 서재에 연결됩니다.

---

## 🩺 기존 `plexhw` & `qbittorrent_gluetun` 8대 근본 원인 진단 및 완치 내역

1. **[CRITICAL] 스택 이원화(`plexhw` vs `qbittorrent_gluetun`) 및 내부 브리지 네트워크(`mediarr_net`) 부재 해결**
   - 분리되어 있던 2개의 컴포즈와 신규 *Arr 서비스들을 단일 `docker-compose.yml`과 전용 `mediarr_net` 브리지 네트워크로 통합하고, 모든 컨테이너 이름을 `mediarr-<서비스명>`(내부 DNS 양방향 별칭 지원)으로 표준화했습니다.
2. **[CRITICAL] Gluetun 방화벽 로컬 서브넷 차단(`FIREWALL_OUTBOUND_SUBNETS` 누락) 및 헬스체크 미선언 완치**
   - `FIREWALL_OUTBOUND_SUBNETS=172.16.0.0/12,192.168.0.0/16,10.0.0.0/8` 및 명시적 `healthcheck`를 내장하고, Gluetun에 `qbittorrent` 네트워크 별칭(alias)을 부여해 Sonarr/Radarr가 `http://qbittorrent:8181`로 막힘없이 통신하도록 해결했습니다.
3. **[HIGH] Prowlarr·FlareSolverr VPN 공유 시 내부 도메인 단절 해결**
   - Gluetun의 `mediarr_net` 네트워크 별칭(`aliases`)에 `qbittorrent`, `prowlarr`, `flaresolverr`를 모두 매핑하여, VPN 터널 경유 모드와 브리지 직결 모드 어느 쪽에서도 `http://prowlarr:9696`, `http://flaresolverr:8191` 표준 주소가 그대로 작동합니다.
4. **[HIGH] Plex 4K 하드웨어 트랜스코딩 2GB RAM 디스크(`tmpfs: /transcode`) 탑재**
   - Intel QuickSync(`/dev/dri`) 가속 시 임시 버퍼가 SSD/HDD를 마모시키지 않도록 `tmpfs: - /transcode:size=2G,mode=1777` RAM 디스크를 추가했습니다.
5. **[HIGH] 실제 업로드된 `plexhw/Library` 정밀 진단: 좀비 `plexmediaserver.pid` 제거 및 2.0GB DB 최적화**
   - 업로드된 `plexhw/Library`에 남아 있던 비정상 종료 잔여 `plexmediaserver.pid` 파일을 즉시 제거하고, Plex(`icu_root` 커스텀 콜레이션 안전 WAL 체크포인트 적용) 및 *Arr 전체 SQLite DB를 최적화(`VACUUM` / `ANALYZE`)했습니다.
6. **[MEDIUM] Watchtower 라벨 완전 제거 및 통합 유지보수 닥터 스크립트 고도화**
7. **[SECURITY] 평문 하드코딩된 Surfshark WireGuard 키·OpenVPN 비밀번호·Plex Claim 토큰 `.env` 보안 분리**
8. **[MEDIUM] 시놀로지 디스크 보호용 전 컨테이너 로그 로테이션(`max-size: 10m, max-file: 3`) 및 메모리 가드 적용**

---

## 🔗 5대 핵심 유기적 자동화 파이프라인

1. **[파이프라인 1] 넷플릭스형 포스터 원클릭 요청 ➔ 즉시 인덱서 자동 검색**
   - `Seerr(:5055)` ➔ `Sonarr(:8989) & Radarr(:7878)` ➔ `Prowlarr(:9696)` + `FlareSolverr(:8191)`
2. **[파이프라인 2] Surfshark VPN 킬스위치 다운로드 ➔ 자동 압축 해제 ➔ 0.1초 하드링크 입수**
   - `Gluetun VPN` + `qBittorrent(:8181)` ➔ `[/data/torrents]` ➔ `Unpackerr` ➔ `Sonarr/Radarr` ➔ `[/data/media/{movies,tv,anime}]`
3. **[파이프라인 3] TRaSH Guides 최고급 화질 프로필 & 한국어 우대 점수 일일 자동 동기화**
   - `Recyclarr` (`recyclarr.yml` 자동 생성) ➔ `Sonarr(:8989) & Radarr(:7878) API`
4. **[파이프라인 4] 한국어 자막 AI 오디오 싱크 보정 ➔ 4K 포스터 배지 ➔ Plex HW + RAM 스트리밍**
   - `Bazarr(:6767)` + `Kometa` ➔ `Plex(:32400)` + `Tautulli(:8182)` + `Maintainerr(:6246)`
5. **[파이프라인 5] 통합 관제 센터(`mediarr-control-center`) 부팅 시 자동 프로비저닝 & 자가 치유 DB 닥터**
   - `mediarr-control-center(:8500, kimmingil/mediarr-stack:latest)` 구동 즉시 전체 폴더 트리 생성, 설정 파일 생성, 잔여 PID 제거 및 SQLite DB 최적화를 수행합니다.

---

## 📦 단일 프로젝트(`docker-compose.yml`) 전체 컨테이너 구성 (총 15대 · Watchtower 제외)

| 번호 | 서비스 | 컨테이너 이름 | 호스트 포트 | 핵심 역할 |
| :---: | :--- | :--- | :---: | :--- |
| 0 | **Mediarr Control Center** | `mediarr-control-center` | `8500` | 본 프로젝트 도커 이미지(`kimmingil/mediarr-stack:latest`) — 폴더/설정 자동 프로비저닝 · DB 최적화 · 통합 관제 |
| 1 | **Gluetun VPN** | `mediarr-gluetun` | `8000` | Surfshark WireGuard/OpenVPN 킬스위치 보안 게이트웨이 (`mediarr_net` 별칭 내장) |
| 2 | **qBittorrent** | `mediarr-qbittorrent` | `8181` / `6881` | 기존 8181 포트·설정·시드 100% 승계 VPN 보호 초고속 토렌트 다운로더 |
| 3 | **Plex Media Server (HW)** | `mediarr-plex` | `32400` | 기존 `/volume1/docker/plexhw` 승계 + QuickSync `/dev/dri` + 2GB RAM 트랜스코딩 |
| 4 | **Seerr (Jellyseerr)** | `mediarr-seerr` | `5055` | 넷플릭스형 영화·드라마·애니 검색 및 원클릭 요청 포털 |
| 5 | **Prowlarr** | `mediarr-prowlarr` | `9696` | 모든 토렌트 인덱서 통합 관리 및 Sonarr·Radarr 실시간 자동 동기화 |
| 6 | **FlareSolverr** | `mediarr-flaresolverr` | `8191` | 인덱서 검색 시 Cloudflare 보안 검증 백그라운드 자동 우회 프록시 |
| 7 | **Sonarr (v4)** | `mediarr-sonarr` | `8989` | TV 드라마·예능·애니메이션 자동 수집 및 `/data/media/{tv,anime}` 0.1초 하드링크 |
| 8 | **Radarr (v5)** | `mediarr-radarr` | `7878` | 영화(4K/1080p) 자동 수집·화질 업그레이드 및 `/data/media/movies` 0.1초 하드링크 |
| 9 | **Bazarr** | `mediarr-bazarr` | `6767` | 한국어(`ko`)·영어(`en`) 자막 자동 다운로드 및 AI 오디오 파형 분석 싱크 보정(`Subsync`) |
| 10 | **Recyclarr** | `mediarr-recyclarr` | 백그라운드 | TRaSH Guides 4K/1080p 화질 프로필 & 캠버전 차단 필터 일일 자동 동기화 |
| 11 | **Unpackerr** | `mediarr-unpackerr` | 백그라운드 | 토렌트 압축파일(`.rar`/`.zip`) 자동 해제 후 하드링크 임포트 연결 |
| 12 | **Tautulli** | `mediarr-tautulli` | `8182` | Plex 실시간 재생·하드웨어 트랜스코딩(HW) 작동 감시 및 통계 대시보드 |
| 13 | **Kometa** | `mediarr-kometa` | 백그라운드 | Plex 포스터 4K·HDR·Dolby Vision·평점 배지 오버레이 및 스마트 컬렉션 생성 |
| 14 | **Maintainerr** | `mediarr-maintainerr` | `6246` | 시청 완료 후 오래 방치된 미디어를 규칙에 따라 자동 정리하는 디스크 용량 수호자 |

---

## 🚀 원클릭 실행 방법

```bash
cp .env.example .env   # (로컬 환경에는 이미 기존 VPN 키와 설정이 이관된 .env가 준비되어 있습니다)
docker compose up -d
```

- 구동 즉시 `mediarr-control-center`(`http://<NAS_IP>:8500`)가 필요한 모든 폴더(`/volume1/docker/...`, `/volume1/mediarr/{torrents,media}/{movies,tv,anime,music}`)와 `recyclarr.yml`, `kometa/config.yml`을 자동 생성하고, 좀비 PID 정리 및 DB 최적화를 수행합니다.
- 용도별 프리셋 스택 파일은 `stacks/` 폴더에도 준비되어 있습니다:
  - `stacks/mediarr-ultimate-stack.yml` (통합 관제 + 14대 미디어 서비스 전체 풀 구성)
  - `stacks/mediarr-core-stack.yml` (통합 관제 + 핵심 9대장 스마트 자동화 구성)
  - `stacks/mediarr-direct-stack.yml` (VPN 미사용 프라이빗 트래커용 초고속 직결 구성)

---

## 📄 라이선스
MIT License
