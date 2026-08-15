import { useEffect, useRef } from "react";

type Props = {
  color?: [number, number, number];
  speed?: number;
  amplitude?: number;
  mouseReact?: boolean;
};

export default function Iridescence({
  color = [0.55, 0.62, 0.82],
  speed = 1.05,
  amplitude = 0.18,
  mouseReact = true,
}: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const propsRef = useRef({ color, speed, amplitude, mouseReact });
  useEffect(() => { propsRef.current = { color, speed, amplitude, mouseReact }; }, [color, speed, amplitude, mouseReact]);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const gl = canvas.getContext("webgl", { alpha: false, antialias: true, premultipliedAlpha: false });
    if (!gl) return;

    const vs = gl.createShader(gl.VERTEX_SHADER)!;
    gl.shaderSource(
      vs,
      `attribute vec2 p; void main(){ gl_Position = vec4(p,0.0,1.0); }`,
    );
    gl.compileShader(vs);

    const fs = gl.createShader(gl.FRAGMENT_SHADER)!;
    gl.shaderSource(
      fs,
      `
      precision highp float;
      uniform vec2 uRes;
      uniform float uTime;
      uniform vec2 uMouse;
      uniform vec3 uColor;
      uniform float uAmp;
      uniform float uSpeed;

      float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453); }
      float noise(vec2 p){
        vec2 i=floor(p); vec2 f=fract(p);
        float a=hash(i), b=hash(i+vec2(1.,0.)), c=hash(i+vec2(0.,1.)), d=hash(i+vec2(1.,1.));
        vec2 u=f*f*(3.-2.*f);
        return mix(a,b,u.x)+(c-a)*u.y*(1.-u.x)+(d-b)*u.x*u.y;
      }

      void main(){
        vec2 uv = (gl_FragCoord.xy / uRes) * 2.0 - 1.0;
        uv.x *= uRes.x / max(uRes.y, 1.0);
        float t = uTime * uSpeed;

        vec2 p = uv * 1.35;
        float n  = noise(p * 1.15 + t * 0.42);
        float n2 = noise(p * 1.9  - t * 0.28);
        float n3 = n * 0.62 + n2 * 0.38;

        float wave = sin(p.x * 1.25 + t * 0.9 + n3 * 2.2) * 0.5
                   + sin(p.y * 1.1  - t * 0.65 + n3 * 1.6) * 0.5
                   + n3 * 0.45;
        wave = wave * 0.5 + 0.5;

        vec3 c1 = uColor;
        vec3 c2 = vec3(0.22, 0.32, 0.56);
        vec3 c3 = vec3(0.80, 0.86, 0.94);
        vec3 col = mix(c1, c2, smoothstep(0.18, 0.78, wave));
        col = mix(col, c3, smoothstep(0.55, 0.92, pow(wave, 2.0)) * 0.38);

        float aspect = uRes.x / max(uRes.y, 1.0);
        vec2 m = vec2(uMouse.x * aspect, uMouse.y);
        float sheen = 0.14 / (length(uv - m) * 1.4 + 0.55);
        col += sheen * vec3(0.92, 0.96, 1.0) * 0.85;

        float d = length(uv * 0.72);
        float vign = smoothstep(1.42, 0.28, d);
        col *= 0.52 + vign * 0.62;
        // micro grain
        col += (hash(gl_FragCoord.xy * 0.6) - 0.5) * 0.012;
        gl_FragColor = vec4(col, 1.0);
      }
      `,
    );
    gl.compileShader(fs);

    const prog = gl.createProgram()!;
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return;
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "p");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    const uRes = gl.getUniformLocation(prog, "uRes");
    const uTime = gl.getUniformLocation(prog, "uTime");
    const uMouse = gl.getUniformLocation(prog, "uMouse");
    const uColor = gl.getUniformLocation(prog, "uColor");
    const uAmp = gl.getUniformLocation(prog, "uAmp");
    const uSpeed = gl.getUniformLocation(prog, "uSpeed");

    const mouse = { x: 0, y: 0, tx: 0, ty: 0 };
    const onMove = (e: MouseEvent) => {
      if (!propsRef.current.mouseReact) return;
      mouse.tx = (e.clientX / window.innerWidth) * 2 - 1;
      mouse.ty = 1 - (e.clientY / window.innerHeight) * 2;
    };
    window.addEventListener("mousemove", onMove);

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.75);
      const w = Math.max(1, Math.floor(canvas.clientWidth * dpr));
      const h = Math.max(1, Math.floor(canvas.clientHeight * dpr));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
        gl.viewport(0, 0, w, h);
      }
    };

    let raf = 0;
    const start = performance.now();
    const tick = () => {
      raf = requestAnimationFrame(tick);
      try {
        resize();
        mouse.x += (mouse.tx - mouse.x) * 0.08;
        mouse.y += (mouse.ty - mouse.y) * 0.08;
        const p = propsRef.current;
        gl.uniform2f(uRes, canvas.width, canvas.height);
        gl.uniform1f(uTime, (performance.now() - start) / 1000);
        gl.uniform2f(uMouse, mouse.x, mouse.y);
        gl.uniform3f(uColor, p.color[0], p.color[1], p.color[2]);
        gl.uniform1f(uAmp, p.amplitude);
        gl.uniform1f(uSpeed, p.speed);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
      } catch {
        cancelAnimationFrame(raf);
      }
    };
    tick();

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("mousemove", onMove);
    };
  }, []);

  return (
    <div className="iri">
      <div className="iri-base" />
      <canvas ref={ref} className="iri-canvas" />
    </div>
  );
}
