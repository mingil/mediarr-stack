const fs = require("fs");

// 1. Restore original filenames (0qyuks3gdh--j.js) in all 6 manifest files from .bak if present
const manifestFiles = [
  "/app/.next/build-manifest.json",
  "/app/.next/fallback-build-manifest.json",
  "/app/.next/server/middleware-build-manifest.js",
  "/app/.next/server/pages/_app/build-manifest.json",
  "/app/.next/static/chunks/0nnbdyhiz~8r3.js",
  "/app/.next/static/chunks/turbopack-05r7ct4tfjyrd.js"
];
for (const f of manifestFiles) {
  if (fs.existsSync(f + ".bak")) {
    fs.copyFileSync(f + ".bak", f);
  }
}

// 2. Patch /app/.next/static/chunks/0qyuks3gdh--j.js
const clientFile = "/app/.next/static/chunks/0qyuks3gdh--j.js";
if (!fs.existsSync(clientFile + ".bak")) {
  fs.copyFileSync(clientFile, clientFile + ".bak");
}
let c = fs.readFileSync(clientFile + ".bak", "utf8");

const oldClientE9 = `let e9=({initialUser:e,children:t})=>{let{user:s,error:i,revalidate:a}=(0,v.useUser)({initialData:e}),l=(0,e8.useRouter)(),o=(0,n.useRef)(!1);return(0,n.useEffect)(()=>{a()},[l.pathname,a]),(0,n.useEffect)(()=>{l.pathname.match(/(setup|login|resetpassword)/)||s&&!i||o.current||(o.current=!0,location.href="/login")},[l,s,i]),(0,r.jsx)(r.Fragment,{children:t})}`;
const newClientE9 = `let e9=({initialUser:e,children:t})=>{let u=e||(typeof window!="undefined"?window.__SEERR_USER__||window.__NEXT_DATA__?.props?.user:void 0),{user:s,error:i,loading:c,revalidate:a}=(0,v.useUser)({initialData:u}),l=(0,e8.useRouter)(),o=(0,n.useRef)(!1);return(0,n.useEffect)(()=>{s&&typeof window!="undefined"&&(window.__SEERR_USER__=s)},[s]),(0,n.useEffect)(()=>{l.pathname.match(/(setup|login|resetpassword)/)||c||s&&(!i||i?.response?.status!==401&&i?.response?.status!==403)||o.current||(o.current=!0,location.href="/login")},[l,s,i,c]),(0,r.jsx)(r.Fragment,{children:t})}`;

const oldClientTcHook = `let{hasPermission:m}=(0,v.useUser)();`;
const newClientTcHook = `typeof window!="undefined"&&(i&&(window.__SEERR_USER__=i),o?.initialized&&(window.__SEERR_SETTINGS__=o));let m=e=>!!((i?.permissions??0)&(2|e));`;

const oldClientGetInit = `else s.pathname.match(/(setup|login\\/plex)/)||(r.res.writeHead(307,{Location:"/setup"}),r.res.end())}let a=await ta.default.getInitialProps(e)`;
const newClientGetInit = `else s.pathname.match(/(setup|login\\/plex)/)||(r.res.writeHead(307,{Location:"/setup"}),r.res.end())}else if(typeof window!="undefined"){t=window.__SEERR_USER__||window.__NEXT_DATA__?.props?.user;i=window.__SEERR_SETTINGS__||window.__NEXT_DATA__?.props?.currentSettings||i;}let a=await ta.default.getInitialProps(e)`;

const oldClientHead = `(0,r.jsx)("title",{children:o.applicationTitle})`;
const newClientHead = `(0,r.jsx)("title",{children:o.applicationTitle}),(0,r.jsx)("script",{dangerouslySetInnerHTML:{__html:"if(!localStorage.getItem('seerr_v3')){localStorage.setItem('seerr_v3','1');Promise.all([fetch('/_next/static/chunks/0qyuks3gdh--j.js',{cache:'reload'}),fetch('/_next/static/chunks/turbopack-05r7ct4tfjyrd.js',{cache:'reload'}),fetch('/_next/static/chunks/0nnbdyhiz~8r3.js',{cache:'reload'})]).then(()=>location.reload())}"}})`;

c = c.replace(oldClientE9, newClientE9)
     .replace(oldClientTcHook, newClientTcHook)
     .replace(oldClientGetInit, newClientGetInit)
     .replace(oldClientHead, newClientHead);
fs.writeFileSync(clientFile, c, "utf8");

// 3. Patch /app/.next/server/chunks/ssr/[root-of-the-server]__0ziftze._.js
const ssrFile = "/app/.next/server/chunks/ssr/[root-of-the-server]__0ziftze._.js";
if (!fs.existsSync(ssrFile + ".bak")) {
  fs.copyFileSync(ssrFile, ssrFile + ".bak");
}
let s = fs.readFileSync(ssrFile + ".bak", "utf8");

const oldSsrUserCtx = `({initialUser:a,children:b})=>{let{user:c,error:h,revalidate:i}=(0,e.useUser)({initialData:a}),j=(0,f.useRouter)(),k=(0,g.useRef)(!1);return(0,g.useEffect)(()=>{i()},[j.pathname,i]),(0,g.useEffect)(()=>{j.pathname.match(/(setup|login|resetpassword)/)||c&&!h||k.current||(k.current=!0,location.href="/login")},[j,c,h]),(0,d.jsx)(d.Fragment,{children:b})}`;
const newSsrUserCtx = `({initialUser:a,children:b})=>{let u=a||(typeof window!="undefined"?window.__SEERR_USER__||window.__NEXT_DATA__?.props?.user:void 0),{user:c,error:h,loading:l,revalidate:i}=(0,e.useUser)({initialData:u}),j=(0,f.useRouter)(),k=(0,g.useRef)(!1);return(0,g.useEffect)(()=>{c&&typeof window!="undefined"&&(window.__SEERR_USER__=c)},[c]),(0,g.useEffect)(()=>{j.pathname.match(/(setup|login|resetpassword)/)||l||c&&(!h||h?.response?.status!==401&&h?.response?.status!==403)||k.current||(k.current=!0,location.href="/login")},[j,c,h,l]),(0,d.jsx)(d.Fragment,{children:b})}`;

const oldSsrBHook = `let{hasPermission:F}=(0,n.useUser)();`;
const newSsrBHook = `typeof window!="undefined"&&(p&&(window.__SEERR_USER__=p),t?.initialized&&(window.__SEERR_SETTINGS__=t));let F=a=>!!((p?.permissions??0)&(2|a));`;

const oldSsrGetInit = `else d.pathname.match(/(setup|login\\/plex)/)||(c.res.writeHead(307,{Location:"/setup"}),c.res.end())}let f=await t.default.getInitialProps(a)`;
const newSsrGetInit = `else d.pathname.match(/(setup|login\\/plex)/)||(c.res.writeHead(307,{Location:"/setup"}),c.res.end())}else if(typeof window!="undefined"){b=window.__SEERR_USER__||window.__NEXT_DATA__?.props?.user;e=window.__SEERR_SETTINGS__||window.__NEXT_DATA__?.props?.currentSettings||e;}let f=await t.default.getInitialProps(a)`;

const oldSsrHead = `(0,d.jsx)("title",{children:t.applicationTitle})`;
const newSsrHead = `(0,d.jsx)("title",{children:t.applicationTitle}),(0,d.jsx)("script",{dangerouslySetInnerHTML:{__html:"if(!localStorage.getItem('seerr_v3')){localStorage.setItem('seerr_v3','1');Promise.all([fetch('/_next/static/chunks/0qyuks3gdh--j.js',{cache:'reload'}),fetch('/_next/static/chunks/turbopack-05r7ct4tfjyrd.js',{cache:'reload'}),fetch('/_next/static/chunks/0nnbdyhiz~8r3.js',{cache:'reload'})]).then(()=>location.reload())}"}})`;

const oldHostPort = `let a=process.env.HOST||"localhost";`;
const newHostPort = `let a=process.env.HOST||"127.0.0.1";`;

s = s.replace(oldSsrUserCtx, newSsrUserCtx)
     .replace(oldSsrBHook, newSsrBHook)
     .replace(oldSsrGetInit, newSsrGetInit)
     .replace(oldSsrHead, newSsrHead)
     .replace(oldHostPort, newHostPort);
fs.writeFileSync(ssrFile, s, "utf8");

// 4. Patch connect-typeorm TypeormStore.js
const storePath = require.resolve("connect-typeorm/out/app/TypeormStore/TypeormStore");
if (!fs.existsSync(storePath + ".bak")) {
  fs.copyFileSync(storePath, storePath + ".bak");
}
let storeCode = fs.readFileSync(storePath + ".bak", "utf8");
const targetTouch = `if ((_a = sess === null || sess === void 0 ? void 0 : sess.cookie) === null || _a === void 0 ? void 0 : _a.expires) {\r\n                this.debug('Skip updating session "%s" expiration', sid);\r\n                if (fn) {\r\n                    fn();\r\n                }\r\n            }`;
const targetTouchLf = targetTouch.replace(/\r\n/g, "\n");
const replacementTouch = `if ((_a = sess === null || sess === void 0 ? void 0 : sess.cookie) === null || _a === void 0 ? void 0 : _a.expires) {\n                this.debug('Skip updating session "%s" expiration', sid);\n                if (fn) {\n                    fn();\n                }\n                return;\n            }`;
storeCode = storeCode.replace(targetTouch, replacementTouch).replace(targetTouchLf, replacementTouch);
fs.writeFileSync(storePath, storeCode, "utf8");

// 5. Patch /app/dist/index.js for SQLite WAL performance pragmas & Cache-Control
const idxPath = "/app/dist/index.js";
if (!fs.existsSync(idxPath + ".bak")) {
  fs.copyFileSync(idxPath, idxPath + ".bak");
}
let idxCode = fs.readFileSync(idxPath + ".bak", "utf8");
const oldPragma = `await dbConnection.query('PRAGMA foreign_keys=ON');`;
const newPragma = `await dbConnection.query('PRAGMA foreign_keys=ON');\n            await dbConnection.query('PRAGMA synchronous=NORMAL');\n            await dbConnection.query('PRAGMA busy_timeout=5000');\n            await dbConnection.query('PRAGMA temp_store=MEMORY');\n            await dbConnection.query('PRAGMA cache_size=-32000');`;
const oldHandle = `server.get('*path', (req, res) => handle(req, res));`;
const newHandle = `server.get('*path', (req, res) => {\n        if (req.url && req.url.includes('/_next/static/chunks/')) {\n            res.setHeader('Cache-Control', 'no-cache, must-revalidate');\n        }\n        return handle(req, res);\n    });`;
idxCode = idxCode.replace(oldPragma, newPragma).replace(oldHandle, newHandle);
fs.writeFileSync(idxPath, idxCode, "utf8");
console.log("All Seerr patches applied successfully!");
