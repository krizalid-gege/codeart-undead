const http = require("http");
const fs = require("fs");
const path = require("path");

const port = Number(process.argv[2] || process.env.APP_PORT || 8080);
const root = path.resolve(__dirname, "..", "site");
const types = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
};

http
  .createServer((req, res) => {
    const rawPath = decodeURIComponent((req.url || "/").split("?")[0]);
    const rel = rawPath === "/" ? "index.html" : rawPath.replace(/^\/+/, "");
    const file = path.resolve(root, rel);
    if (!file.startsWith(root)) {
      res.writeHead(403).end("forbidden");
      return;
    }
    fs.readFile(file, (err, data) => {
      if (err) {
        res.writeHead(404, { "content-type": "text/plain; charset=utf-8" }).end("not found");
        return;
      }
      res.writeHead(200, { "content-type": types[path.extname(file)] || "application/octet-stream" }).end(data);
    });
  })
  .listen(port, "0.0.0.0", () => console.log(`static server on ${port}`));