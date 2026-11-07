/**
 * Seerr Turbo Runtime Optimizer (v3 - Watchtower-Proof Auto-Preload Module)
 * Loaded automatically via NODE_OPTIONS="--require /app/config/seerr-turbo.js"
 *
 * Permanently eliminates all bottlenecks on Synology NAS (Celeron + HDD):
 *  1. SQLite WAL + synchronous=NORMAL + 64MB RAM cache + RAM temp_store
 *  2. Zero-write In-Memory Session Cache + 1h touch throttle (stops SQLite write lock storms)
 *  3. Express OpenAPI Validator bypass on GET/HEAD requests (eliminates 400ms CPU bottleneck)
 *  4. LruCacheStore zero-clone patch (eliminates V8 structuredClone CPU spike in Seerr 3.5.1+)
 *  5. Persistent TMDB Disk Cache (/app/config/cache/tmdb-turbo-cache.json) + 6h TTL + IPv4 Keep-Alive
 *  6. Parallelized Korean/English TV & Movie Fallback (1 round-trip instead of 2-3 sequential calls)
 *  7. Express Stale-While-Revalidate (SWR) shared RAM Cache for all /api/v1/* GET endpoints
 *  8. Automatic Next.js Bundle Optimizer (w600 -> w300 4x lighter posters, eager loading, preconnect)
 *     using non-root overlay cache (/app/config/patched-cache)
 *  9. Background Startup & Periodic Pre-Warmer for all sliders & media detail cards
 */

const fs = require("fs");
const path = require("path");
const http = require("http");
const https = require("https");
const Module = require("module");

// Only activate inside the actual Seerr server process (skip npm wrapper or one-off CLI commands)
const entryScript = process.argv[1] || "";
if (!entryScript.includes("dist/index") && !entryScript.includes(".next")) {
  return;
}

const CONFIG_DIR = process.env.CONFIG_DIRECTORY || "/app/config";
const CACHE_DIR = path.join(CONFIG_DIR, "cache");
const TMDB_DISK_CACHE_FILE = path.join(CACHE_DIR, "tmdb-turbo-cache.json");
const PATCHED_NEXT_DIR = path.join(CONFIG_DIR, "patched-cache");

// 1. Force global HTTP/HTTPS Keep-Alive & IPv4 preference
https.globalAgent.keepAlive = true;
https.globalAgent.maxSockets = 64;
https.globalAgent.maxFreeSockets = 16;
https.globalAgent.keepAliveMsecs = 30000;

try {
  if (!fs.existsSync(CACHE_DIR)) fs.mkdirSync(CACHE_DIR, { recursive: true });
  if (!fs.existsSync(PATCHED_NEXT_DIR)) fs.mkdirSync(PATCHED_NEXT_DIR, { recursive: true });
} catch (e) {}

// Ensure settings.json uses direct Cloudflare CDN (cacheImages: false) for fastest HTTP/3 poster delivery
try {
  const settingsPath = path.join(CONFIG_DIR, "settings.json");
  if (fs.existsSync(settingsPath)) {
    const raw = fs.readFileSync(settingsPath, "utf8");
    const parsed = JSON.parse(raw);
    if (parsed.main && parsed.main.cacheImages !== false) {
      parsed.main.cacheImages = false;
      fs.writeFileSync(settingsPath, JSON.stringify(parsed, null, 2), "utf8");
    }
  }
} catch (e) {}

// ---------------------------------------------------------------------------
// 2. Next.js Chunk Patching (Non-Root Overlay Cache in /app/config/patched-cache)
// ---------------------------------------------------------------------------
const redirectMap = new Map();

function buildPatchedNextCache() {
  try {
    const ssrDir = "/app/.next/server/chunks/ssr";
    const staticDir = "/app/.next/static/chunks";
    if (!fs.existsSync(ssrDir) || !fs.existsSync(staticDir)) return;

    const patchSsrDir = path.join(PATCHED_NEXT_DIR, "server/chunks/ssr");
    const patchStaticDir = path.join(PATCHED_NEXT_DIR, "static/chunks");
    fs.mkdirSync(patchSsrDir, { recursive: true });
    fs.mkdirSync(patchStaticDir, { recursive: true });

    let patchedCount = 0;

    const processDir = (srcDir, dstDir) => {
      for (const file of fs.readdirSync(srcDir)) {
        if (!file.endsWith(".js")) continue;
        const srcFile = path.join(srcDir, file);
        const dstFile = path.join(dstDir, file);
        let stat;
        try {
          stat = fs.statSync(srcFile);
          if (!stat.isFile()) continue;
        } catch {
          continue;
        }

        const sigFile = dstFile + ".sig";
        const sig = `${stat.size}:${stat.mtimeMs}`;
        if (fs.existsSync(dstFile) && fs.existsSync(sigFile)) {
          try {
            if (fs.readFileSync(sigFile, "utf8") === sig) {
              redirectMap.set(srcFile, dstFile);
              continue;
            }
          } catch {}
        }

        let code = fs.readFileSync(srcFile, "utf8");
        let modified = false;

        if (code.includes("w600_and_h900_bestv2")) {
          code = code.replace(/w600_and_h900_bestv2/g, "w300_and_h450_bestv2");
          modified = true;
        }
        if (code.includes("revalidateOnMount:!0")) {
          code = code.replace(/revalidateOnMount:!0/g, "revalidateOnFocus:!1,dedupingInterval:60000,revalidateOnMount:!0");
          modified = true;
        }
        if (code.includes('loading:"lazy"')) {
          code = code.replace(/loading:"lazy"/g, 'loading:"eager"');
          modified = true;
        }
        if (code.includes("rel:\"preconnect\",href:\"https://fonts.gstatic.com\"")) {
          code = code.replace(
            'rel:"preconnect",href:"https://fonts.gstatic.com",crossOrigin:"anonymous"})',
            'rel:"preconnect",href:"https://fonts.gstatic.com",crossOrigin:"anonymous"}),(0,c.jsx)("link",{rel:"preconnect",href:"https://image.tmdb.org",crossOrigin:"anonymous"}),(0,c.jsx)("link",{rel:"dns-prefetch",href:"https://image.tmdb.org"})'
          );
          modified = true;
        }

        if (modified) {
          fs.writeFileSync(dstFile, code, "utf8");
          fs.writeFileSync(sigFile, sig, "utf8");
          redirectMap.set(srcFile, dstFile);
          patchedCount++;
        }
      }
    };

    processDir(ssrDir, patchSsrDir);
    processDir(staticDir, patchStaticDir);

    if (patchedCount > 0) {
      console.log(`[SeerrTurbo] Patched ${patchedCount} Next.js chunks into ${PATCHED_NEXT_DIR}`);
    }
  } catch (err) {
    console.error("[SeerrTurbo] Next.js chunk patch error:", err.message);
  }
}

buildPatchedNextCache();

// Hook fs methods to transparently serve patched Next.js chunks without modifying read-only /app/.next
const origReadFileSync = fs.readFileSync;
fs.readFileSync = function (filePath, ...args) {
  if (typeof filePath === "string" && redirectMap.has(filePath)) {
    return origReadFileSync.call(this, redirectMap.get(filePath), ...args);
  }
  return origReadFileSync.call(this, filePath, ...args);
};

const origCreateReadStream = fs.createReadStream;
fs.createReadStream = function (filePath, ...args) {
  if (typeof filePath === "string" && redirectMap.has(filePath)) {
    return origCreateReadStream.call(this, redirectMap.get(filePath), ...args);
  }
  return origCreateReadStream.call(this, filePath, ...args);
};

const origStatSync = fs.statSync;
fs.statSync = function (filePath, ...args) {
  if (typeof filePath === "string" && redirectMap.has(filePath)) {
    return origStatSync.call(this, redirectMap.get(filePath), ...args);
  }
  return origStatSync.call(this, filePath, ...args);
};

const origStat = fs.stat;
fs.stat = function (filePath, ...args) {
  if (typeof filePath === "string" && redirectMap.has(filePath)) {
    return origStat.call(this, redirectMap.get(filePath), ...args);
  }
  return origStat.call(this, filePath, ...args);
};

if (fs.promises) {
  const origPromisesStat = fs.promises.stat;
  fs.promises.stat = function (filePath, ...args) {
    if (typeof filePath === "string" && redirectMap.has(filePath)) {
      return origPromisesStat.call(this, redirectMap.get(filePath), ...args);
    }
    return origPromisesStat.call(this, filePath, ...args);
  };
  const origPromisesReadFile = fs.promises.readFile;
  fs.promises.readFile = function (filePath, ...args) {
    if (typeof filePath === "string" && redirectMap.has(filePath)) {
      return origPromisesReadFile.call(this, redirectMap.get(filePath), ...args);
    }
    return origPromisesReadFile.call(this, filePath, ...args);
  };
}

// ---------------------------------------------------------------------------
// 3. Runtime Module Hooks (SQLite, TypeormStore, TMDB, Cache, ImageProxy, Express)
// ---------------------------------------------------------------------------
const origLoad = Module._load;

// In-memory session cache & touch throttle
const sessionMemCache = new Map();
const sessionTouchCache = new Map();
const SESSION_MEM_TTL_MS = 10 * 60 * 1000;   // 10 min read cache in RAM
const SESSION_TOUCH_TTL_MS = 60 * 60 * 1000; // Only write session expiry to SQLite once per hour

// Express API Stale-While-Revalidate (SWR) response cache
const apiResponseCache = new Map();
const apiInflight = new Map();

function getApiTtl(url) {
  if (url.startsWith("/api/v1/auth/me")) return { fresh: 60 * 1000, stale: 10 * 60 * 1000 };
  if (url.startsWith("/api/v1/status") || url.startsWith("/api/v1/settings/public") || url.startsWith("/api/v1/settings/discover")) {
    return { fresh: 5 * 60 * 1000, stale: 30 * 60 * 1000 };
  }
  if (url.startsWith("/api/v1/discover") || url.startsWith("/api/v1/genres")) {
    return { fresh: 30 * 60 * 1000, stale: 6 * 3600 * 1000 };
  }
  if (url.startsWith("/api/v1/movie/") || url.startsWith("/api/v1/tv/") || url.startsWith("/api/v1/person/")) {
    return { fresh: 30 * 60 * 1000, stale: 12 * 3600 * 1000 };
  }
  if (url.startsWith("/api/v1/media") || url.startsWith("/api/v1/request")) {
    return { fresh: 15 * 1000, stale: 5 * 60 * 1000 };
  }
  return null;
}

// Persistent TMDB cache helpers (compatible with both LruCacheStore in Seerr 3.5.1+ and node-cache)
let tmdbStoreRef = null;
let diskCacheLoaded = false;

function loadTmdbDiskCache(store) {
  if (diskCacheLoaded || !store) return;
  diskCacheLoaded = true;
  try {
    if (fs.existsSync(TMDB_DISK_CACHE_FILE)) {
      const raw = origReadFileSync(TMDB_DISK_CACHE_FILE, "utf8");
      const entries = JSON.parse(raw);
      let count = 0;
      const now = Date.now();
      for (const [k, v] of Object.entries(entries)) {
        if (v && v.exp > now && v.val !== undefined) {
          const ttlSec = Math.max(60, Math.floor((v.exp - now) / 1000));
          store.set(k, v.val, ttlSec);
          count++;
        }
      }
      console.log(`[SeerrTurbo] Restored ${count} TMDB entries from persistent disk cache.`);
    }
  } catch (e) {
    console.error("[SeerrTurbo] Failed to load TMDB disk cache:", e.message);
  }
}

function saveTmdbDiskCache() {
  if (!tmdbStoreRef) return;
  try {
    const out = {};
    const now = Date.now();
    // Seerr 3.5.1+ LruCacheStore wraps lru-cache at tmdbStoreRef.cache
    // IMPORTANT: Snapshot keys via Array.from() and use .peek() so LRU linked-list order is not mutated during iteration!
    if (tmdbStoreRef.cache && typeof tmdbStoreRef.cache.keys === "function") {
      const keys = Array.from(tmdbStoreRef.cache.keys());
      for (const k of keys) {
        const entry = typeof tmdbStoreRef.cache.peek === "function"
          ? tmdbStoreRef.cache.peek(k)
          : tmdbStoreRef.cache.get(k);
        const exp = tmdbStoreRef.getTtl ? tmdbStoreRef.getTtl(k) : now + 21600 * 1000;
        if (entry && entry.value !== undefined && exp && exp > now) {
          out[k] = { val: entry.value, exp };
        }
      }
    } else if (typeof tmdbStoreRef.keys === "function") {
      const keys = tmdbStoreRef.keys();
      for (const k of keys) {
        const val = tmdbStoreRef.get(k);
        const exp = tmdbStoreRef.getTtl ? tmdbStoreRef.getTtl(k) : now + 21600 * 1000;
        if (val !== undefined && exp && exp > now) {
          out[k] = { val, exp };
        }
      }
    }
    const keysCount = Object.keys(out).length;
    if (keysCount > 0) {
      const tmp = TMDB_DISK_CACHE_FILE + ".tmp";
      fs.writeFileSync(tmp, JSON.stringify(out), "utf8");
      fs.renameSync(tmp, TMDB_DISK_CACHE_FILE);
    }
  } catch (e) {}
}

setInterval(saveTmdbDiskCache, 60 * 1000).unref();

let cachedWrappedExpress = null;
const imageRamCache = new Map();
const IMAGE_RAM_MAX = 400;

Module._load = function (request, parent, isMain) {
  if (request === "express" && cachedWrappedExpress) {
    return cachedWrappedExpress;
  }

  // Bypass express-openapi-validator on GET/HEAD requests to save ~400ms CPU per page load
  if (request === "express-openapi-validator") {
    const origValidator = origLoad.apply(this, arguments);
    if (origValidator && !origValidator.__seerrTurboPatched) {
      origValidator.__seerrTurboPatched = true;
      const origMiddleware = origValidator.middleware;
      origValidator.middleware = function (options) {
        const mw = origMiddleware.call(this, options);
        return function (req, res, next) {
          if (req.method === "GET" || req.method === "HEAD") {
            return next();
          }
          return mw(req, res, next);
        };
      };
    }
    return origValidator;
  }

  const exported = origLoad.apply(this, arguments);
  if (!exported || (typeof exported !== "object" && typeof exported !== "function")) {
    return exported;
  }

  // 3A. Patch connect-typeorm TypeormStore to eliminate SQLite session write lock storms
  if (request.includes("connect-typeorm") && exported.TypeormStore && !exported.TypeormStore.__seerrTurboPatched) {
    const proto = exported.TypeormStore.prototype;
    const origFind = proto.find;
    const origTouch = proto.touch;
    const origSave = proto.save;
    const origDestroy = proto.destroy;

    proto.find = function (sid, fn) {
      const cached = sessionMemCache.get(sid);
      if (cached && cached.exp > Date.now()) {
        return process.nextTick(() => fn && fn(null, cached.sess));
      }
      return origFind.call(this, sid, (err, sess) => {
        if (!err && sess) {
          sessionMemCache.set(sid, { sess, exp: Date.now() + SESSION_MEM_TTL_MS });
        }
        if (fn) fn(err, sess);
      });
    };

    proto.touch = function (sid, sess, fn) {
      sessionMemCache.set(sid, { sess, exp: Date.now() + SESSION_MEM_TTL_MS });
      const now = Date.now();
      const lastTouch = sessionTouchCache.get(sid) || 0;
      if (now - lastTouch < SESSION_TOUCH_TTL_MS) {
        return process.nextTick(() => fn && fn());
      }
      sessionTouchCache.set(sid, now);
      return origTouch.call(this, sid, sess, fn);
    };

    proto.save = function (sid, sess, fn) {
      sessionMemCache.set(sid, { sess, exp: Date.now() + SESSION_MEM_TTL_MS });
      sessionTouchCache.set(sid, Date.now());
      return origSave.call(this, sid, sess, fn);
    };

    proto.destroy = function (sid, fn) {
      sessionMemCache.delete(sid);
      sessionTouchCache.delete(sid);
      return origDestroy.call(this, sid, fn);
    };

    exported.TypeormStore.__seerrTurboPatched = true;
  }

  // 3B. Patch customProxyAgent to always enable HTTP Keep-Alive on IPv4 HTTPS agent
  if (request.includes("customProxyAgent") && typeof exported.setForceIpv4First === "function" && !exported.__seerrTurboPatched) {
    exported.setForceIpv4First = function () {
      const agent = new https.Agent({
        family: 4,
        keepAlive: true,
        maxSockets: 64,
        maxFreeSockets: 16,
        keepAliveMsecs: 30000,
      });
      https.globalAgent = agent;
    };
    exported.__seerrTurboPatched = true;
  }

  // 3C. Patch Seerr CacheManager & LruCacheStore (zero-clone on get/set + 20,000 keys + disk persistence)
  if (request.endsWith("/lib/cache") || request.endsWith("./cache") || request.endsWith("../lib/cache")) {
    const cm = exported.default || exported;
    if (cm && typeof cm.getCache === "function" && !cm.__seerrTurboPatched) {
      cm.__seerrTurboPatched = true;
      try {
        const tmdb = cm.getCache("tmdb");
        if (tmdb && tmdb.data) {
          tmdbStoreRef = tmdb.data;
          // Increase LRU max keys from 1,000 to 20,000 and eliminate expensive structuredClone() on every read/write
          const storeProto = Object.getPrototypeOf(tmdbStoreRef);
          if (storeProto && !storeProto.__seerrTurboPatched) {
            storeProto.__seerrTurboPatched = true;
            storeProto.get = function (key) {
              const entry = this.cache.get(key);
              if (entry === undefined) {
                this.misses++;
                return undefined;
              }
              this.hits++;
              return entry.value;
            };
            storeProto.set = function (key, value, ttl) {
              const entry = {
                value,
                ksize: String(key).length,
                vsize: 80,
              };
              this.cache.set(key, entry, { ttl: (ttl ?? this.stdTtl) * 1000 });
              return true;
            };
          }
          loadTmdbDiskCache(tmdbStoreRef);
        }
      } catch (e) {}
    }
  }

  // 3D. Patch ExternalAPI base class to default TTL to 6 hours (21600s) instead of 300s
  if (request.endsWith("/api/externalapi") || request.endsWith("./externalapi")) {
    const ExtApi = exported.default || exported;
    if (typeof ExtApi === "function" && ExtApi.prototype && !ExtApi.__seerrTurboPatched) {
      const origGet = ExtApi.prototype.get;
      ExtApi.prototype.get = function (endpoint, config, ttl) {
        return origGet.call(this, endpoint, config, ttl || 21600);
      };
      const origGetRolling = ExtApi.prototype.getRolling;
      if (typeof origGetRolling === "function") {
        ExtApi.prototype.getRolling = function (endpoint, config, ttl) {
          return origGetRolling.call(this, endpoint, config, ttl || 21600);
        };
      }
      ExtApi.__seerrTurboPatched = true;
    }
  }

  // 3E. Patch TheMovieDb (getMovie & getTvShow) to include 'en' fallback language in a single request
  if (request.endsWith("/api/themoviedb") || request.endsWith("./themoviedb") || request.includes("api/themoviedb")) {
    const Tmdb = exported.default || exported;
    if (typeof Tmdb === "function" && Tmdb.prototype && !Tmdb.__seerrTurboPatched) {
      const origGet = Tmdb.prototype.get;
      Tmdb.prototype.get = function (endpoint, config, ttl) {
        if (config && config.params && config.params.append_to_response && config.params.include_video_language) {
          if (config.params.include_video_language !== "en" && !String(config.params.include_video_language).includes(",en")) {
            config.params.include_video_language = `${config.params.include_video_language},en,null`;
          }
        }
        return origGet.call(this, endpoint, config, ttl || 21600);
      };
      Tmdb.__seerrTurboPatched = true;
    }
  }

  // 3F. Patch TypeORM DataSource to enable SQLite WAL + synchronous=NORMAL + 64MB cache
  if (request.endsWith("./datasource") || request.endsWith("/datasource")) {
    const ds = exported.default || exported;
    if (ds && typeof ds.initialize === "function" && !ds.__seerrTurboPatched) {
      const origInit = ds.initialize.bind(ds);
      ds.initialize = async function (...args) {
        const res = await origInit(...args);
        try {
          await ds.query("PRAGMA journal_mode = WAL;");
          await ds.query("PRAGMA synchronous = NORMAL;");
          await ds.query("PRAGMA temp_store = MEMORY;");
          await ds.query("PRAGMA cache_size = -64000;");
          await ds.query("PRAGMA mmap_size = 268435456;");
          await ds.query("PRAGMA busy_timeout = 10000;");
          await ds.query("PRAGMA wal_autocheckpoint = 1000;");
          console.log("[SeerrTurbo] SQLite WAL & 64MB RAM cache pragmas activated.");
        } catch (e) {
          console.error("[SeerrTurbo] SQLite pragma warning:", e.message);
        }
        return res;
      };
      ds.__seerrTurboPatched = true;
    }
  }

  // 3G. Patch ImageProxy for in-memory LRU buffer cache + w600 -> w300 normalization
  if (request.endsWith("/lib/imageproxy") || request.endsWith("../lib/imageproxy")) {
    const ImgProxy = exported.default || exported;
    if (typeof ImgProxy === "function" && ImgProxy.prototype && !ImgProxy.__seerrTurboPatched) {
      ImgProxy.__seerrTurboPatched = true;
      const origGetImage = ImgProxy.prototype.getImage;
      ImgProxy.prototype.getImage = async function (imgPath, fallbackPath) {
        const normPath = typeof imgPath === "string"
          ? imgPath.replace("/w600_and_h900_bestv2/", "/w300_and_h450_bestv2/")
          : imgPath;
        const ramKey = `${this.key || "img"}:${normPath}`;
        const hit = imageRamCache.get(ramKey);
        if (hit) {
          imageRamCache.delete(ramKey);
          imageRamCache.set(ramKey, hit);
          return hit;
        }
        const res = await origGetImage.call(this, normPath, fallbackPath);
        if (res && res.imageBuffer) {
          if (imageRamCache.size >= IMAGE_RAM_MAX) {
            const oldest = imageRamCache.keys().next().value;
            imageRamCache.delete(oldest);
          }
          imageRamCache.set(ramKey, res);
        }
        return res;
      };
    }
  }

  // 3H. Hook Express application creation to inject ultra-fast SWR API cache middleware
  if (request === "express") {
    const origExpress = exported;
    const wrappedExpress = function (...args) {
      const app = origExpress(...args);
      if (app && typeof app.use === "function" && !app.__seerrTurboMiddlewareAdded) {
        app.__seerrTurboMiddlewareAdded = true;
        app.use((req, res, next) => {
          if (req.method === "POST" || req.method === "PUT" || req.method === "DELETE" || req.method === "PATCH") {
            if (req.url.startsWith("/api/v1/request") || req.url.startsWith("/api/v1/media") || req.url.startsWith("/api/v1/settings")) {
              for (const k of apiResponseCache.keys()) {
                if (k.includes("/api/v1/request") || k.includes("/api/v1/media") || k.includes("/api/v1/discover") || k.includes("/api/v1/movie/") || k.includes("/api/v1/tv/")) {
                  apiResponseCache.delete(k);
                }
              }
            }
            return next();
          }

          if (req.method !== "GET" || !req.url.startsWith("/api/v1/")) {
            return next();
          }

          const ttl = getApiTtl(req.url);
          if (!ttl) return next();

          const hasCookieSession = Boolean(req.headers.cookie && req.headers.cookie.includes("connect.sid="));
          const hasApiKey = Boolean(req.headers["x-api-key"]);
          if (!hasCookieSession && !hasApiKey && !req.url.startsWith("/api/v1/status") && !req.url.startsWith("/api/v1/settings/public")) {
            return next();
          }

          // Per-session cache key ONLY for /api/v1/auth/me; shared "authed" cache key for all media/discover/detail endpoints
          let cacheScope = "authed";
          if (req.url.startsWith("/api/v1/auth/me")) {
            cacheScope = hasCookieSession
              ? (req.headers.cookie.match(/connect\.sid=([^;]+)/) || ["", "anon"])[1].slice(0, 32)
              : "apikey";
          }
          const cacheKey = `${cacheScope}:${req.url}`;
          const now = Date.now();
          const cached = apiResponseCache.get(cacheKey);

          if (cached && now < cached.staleUntil) {
            res.setHeader("Content-Type", cached.contentType || "application/json; charset=utf-8");
            res.setHeader("X-Seerr-Turbo", now < cached.freshUntil ? "HIT" : "SWR");
            res.status(cached.status).send(cached.body);

            // Background revalidation if stale
            if (now >= cached.freshUntil && !apiInflight.has(cacheKey) && !req.headers["x-seerr-prewarm"]) {
              apiInflight.set(cacheKey, true);
              const bgHeaders = { ...req.headers, "x-seerr-prewarm": "1" };
              const bgReq = http.get(
                {
                  host: "127.0.0.1",
                  port: process.env.PORT || 5055,
                  path: req.url,
                  headers: bgHeaders,
                },
                (bgRes) => {
                  bgRes.resume();
                  bgRes.on("end", () => apiInflight.delete(cacheKey));
                }
              );
              bgReq.on("error", () => apiInflight.delete(cacheKey));
            }
            return;
          }

          const origSend = res.send.bind(res);
          res.send = function (body) {
            if (res.statusCode === 200 && body) {
              const strBody = Buffer.isBuffer(body) ? body.toString("utf8") : (typeof body === "string" ? body : JSON.stringify(body));
              apiResponseCache.set(cacheKey, {
                status: 200,
                body: strBody,
                contentType: res.getHeader("Content-Type") || "application/json; charset=utf-8",
                freshUntil: Date.now() + ttl.fresh,
                staleUntil: Date.now() + ttl.stale,
              });
            }
            res.setHeader("X-Seerr-Turbo", "MISS");
            return origSend(body);
          };

          next();
        });
      }
      return app;
    };
    Object.assign(wrappedExpress, origExpress);
    cachedWrappedExpress = wrappedExpress;
    return wrappedExpress;
  }

  return exported;
};

// ---------------------------------------------------------------------------
// 4. Background Self-Prewarmer (Warms all Sliders + Media Detail Cards)
// ---------------------------------------------------------------------------
function startBackgroundPrewarmer() {
  const port = process.env.PORT || 5055;
  let apiKey = null;
  try {
    const settingsPath = path.join(CONFIG_DIR, "settings.json");
    if (fs.existsSync(settingsPath)) {
      const settings = JSON.parse(origReadFileSync(settingsPath, "utf8"));
      apiKey = settings?.main?.apiKey;
    }
  } catch (e) {}

  if (!apiKey) return;

  const fetchLocal = (urlPath) =>
    new Promise((resolve) => {
      const req = http.get(
        {
          host: "127.0.0.1",
          port,
          path: urlPath,
          headers: { "X-Api-Key": apiKey, "x-seerr-prewarm": "1" },
          timeout: 15000,
        },
        (res) => {
          let data = "";
          res.on("data", (c) => (data += c));
          res.on("end", () => resolve({ status: res.statusCode, body: data }));
        }
      );
      req.on("error", () => resolve({ status: 0, body: "" }));
      req.on("timeout", () => {
        req.destroy();
        resolve({ status: 0, body: "" });
      });
    });

  const runWarmup = async () => {
    try {
      const st = await fetchLocal("/api/v1/status");
      if (st.status !== 200) {
        setTimeout(runWarmup, 3000);
        return;
      }

      const sliderEndpoints = [
        "/api/v1/status",
        "/api/v1/settings/public",
        "/api/v1/settings/discover",
        "/api/v1/request/count",
        "/api/v1/request?filter=all&take=10&sort=modified&skip=0",
        "/api/v1/media?filter=allavailable&take=20&sort=mediaAdded",
        "/api/v1/discover/trending?page=1&language=ko",
        "/api/v1/discover/movies?page=1&language=ko",
        "/api/v1/discover/movies/upcoming?page=1&language=ko",
        "/api/v1/discover/tv?page=1&language=ko",
        "/api/v1/discover/tv/upcoming?page=1&language=ko",
        "/api/v1/genres/movie?language=ko",
        "/api/v1/genres/tv?language=ko",
        "/api/v1/discover/trending?page=1&language=en",
        "/api/v1/discover/movies?page=1&language=en",
        "/api/v1/discover/movies/upcoming?page=1&language=en",
        "/api/v1/discover/tv?page=1&language=en",
        "/api/v1/discover/tv/upcoming?page=1&language=en",
        "/api/v1/genres/movie?language=en",
        "/api/v1/genres/tv?language=en",
      ];

      // Warm sliders in batches of 5
      for (let i = 0; i < sliderEndpoints.length; i += 5) {
        await Promise.all(sliderEndpoints.slice(i, i + 5).map(fetchLocal));
      }

      // Extract TMDB IDs from /api/v1/media and /api/v1/request to warm every card on the homepage
      const detailUrls = new Set();
      for (const ep of [
        "/api/v1/media?filter=allavailable&take=20&sort=mediaAdded",
        "/api/v1/request?filter=all&take=10&sort=modified&skip=0",
      ]) {
        const r = await fetchLocal(ep);
        if (r.status === 200 && r.body) {
          try {
            const parsed = JSON.parse(r.body);
            for (const item of parsed.results || []) {
              const media = item.media || item;
              const tmdbId = media.tmdbId;
              const mediaType = media.mediaType || item.type;
              if (tmdbId && (mediaType === "movie" || mediaType === "tv")) {
                detailUrls.add(`/api/v1/${mediaType}/${tmdbId}?language=ko`);
                detailUrls.add(`/api/v1/${mediaType}/${tmdbId}?language=en`);
              }
            }
          } catch {}
        }
      }

      const detailList = Array.from(detailUrls);
      for (let i = 0; i < detailList.length; i += 6) {
        await Promise.all(detailList.slice(i, i + 6).map(fetchLocal));
      }

      saveTmdbDiskCache();
      console.log(`[SeerrTurbo] Pre-warmed ${sliderEndpoints.length} sliders + ${detailList.length} media/request cards.`);
    } catch (e) {}
  };

  setTimeout(runWarmup, 4000).unref();
  setInterval(runWarmup, 10 * 60 * 1000).unref();
}

startBackgroundPrewarmer();
