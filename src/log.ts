function format(msg: string, args: unknown[]): string {
  if (args.length === 0) return msg;
  let i = 0;
  const out = msg.replace(/%[sdif]|%\.\d+f/g, (match) => {
    if (i >= args.length) return match;
    const value = args[i++];
    if (match.startsWith("%.")) {
      const digits = parseInt(match.slice(2, -1), 10);
      return Number(value).toFixed(digits);
    }
    if (match === "%d" || match === "%i") return String(Math.trunc(Number(value)));
    if (match === "%f") return String(Number(value));
    return String(value);
  });
  return i < args.length ? `${out} ${args.slice(i).map(String).join(" ")}` : out;
}

export function createLogger(name: string) {
  const prefix = `[${name}]`;
  return {
    info(msg: string, ...args: unknown[]) {
      console.log(prefix, format(msg, args));
    },
    warn(msg: string, ...args: unknown[]) {
      console.warn(prefix, format(msg, args));
    },
    error(msg: string, ...args: unknown[]) {
      console.error(prefix, format(msg, args));
    },
    debug(msg: string, ...args: unknown[]) {
      if (process.env.DEBUG) console.debug(prefix, format(msg, args));
    },
  };
}
