// @ts-nocheck — Three.js types not bundled in this version
'use client';

import { useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Float, Points, PointMaterial, Line } from '@react-three/drei';
import * as THREE from 'three';

function ParticleField() {
  const ref = useRef<any>(null);

  const [positions, colors] = useMemo(() => {
    const count = 3000;
    const pos = new Float32Array(count * 3);
    const col = new Float32Array(count * 3);
    const palette = [
      new THREE.Color('#13E0C2'),
      new THREE.Color('#2A35E0'),
      new THREE.Color('#3A45E8'),
      new THREE.Color('#1E27B8'),
    ];
    for (let i = 0; i < count; i++) {
      const radius = 5 + Math.random() * 15;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      pos[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
      pos[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
      pos[i * 3 + 2] = radius * Math.cos(phi);
      const c = palette[Math.floor(Math.random() * palette.length)];
      col[i * 3] = c.r;
      col[i * 3 + 1] = c.g;
      col[i * 3 + 2] = c.b;
    }
    return [pos, col];
  }, []);

  useFrame((state: any) => {
    if (ref.current) {
      ref.current.rotation.y = state.clock.elapsedTime * 0.015;
      ref.current.rotation.x = Math.sin(state.clock.elapsedTime * 0.01) * 0.05;
    }
  });

  return (
    <Points ref={ref} positions={positions} colors={colors} stride={3} frustumCulled={false}>
      <PointMaterial
        transparent
        vertexColors
        size={0.06}
        sizeAttenuation
        depthWrite={false}
        opacity={0.8}
        blending={THREE.AdditiveBlending}
      />
    </Points>
  );
}

function Globe() {
  const ref = useRef<any>(null);
  const wireRef = useRef<any>(null);

  useFrame((state: any) => {
    if (ref.current) {
      ref.current.rotation.y = state.clock.elapsedTime * 0.08;
      ref.current.rotation.x = Math.sin(state.clock.elapsedTime * 0.03) * 0.05;
    }
    if (wireRef.current) {
      wireRef.current.rotation.y = state.clock.elapsedTime * 0.06;
      wireRef.current.rotation.x = Math.sin(state.clock.elapsedTime * 0.04) * 0.08;
    }
  });

  return (
    <group>
      <mesh ref={ref}>
        <icosahedronGeometry args={[2.2, 4]} />
        <meshBasicMaterial color="#2A35E0" wireframe transparent opacity={0.08} />
      </mesh>
      <mesh ref={wireRef}>
        <icosahedronGeometry args={[2.2, 1]} />
        <meshBasicMaterial color="#13E0C2" wireframe transparent opacity={0.15} />
      </mesh>
    </group>
  );
}

function OrbitingRing({ radius, color, speed, tilt }: { radius: number; color: string; speed: number; tilt?: number }) {
  const ref = useRef<any>(null);
  const points = useMemo(() => {
    const pts = [];
    const segments = 64;
    for (let i = 0; i <= segments; i++) {
      const theta = (i / segments) * Math.PI * 2;
      pts.push(new THREE.Vector3(Math.cos(theta) * radius, 0, Math.sin(theta) * radius));
    }
    return pts;
  }, [radius]);

  useFrame((state: any) => {
    if (ref.current) {
      ref.current.rotation.x = tilt || Math.PI * 0.3;
      ref.current.rotation.z = state.clock.elapsedTime * speed;
    }
  });

  return (
    <line ref={ref}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={points.length}
          array={new Float32Array(points.flatMap(v => [v.x, v.y, v.z]))}
          itemSize={3}
        />
      </bufferGeometry>
      <lineBasicMaterial color={color} transparent opacity={0.15} />
    </line>
  );
}

function Scene() {
  return (
    <>
      <ParticleField />
      <Globe />
      <OrbitingRing radius={3.5} color="#13E0C2" speed={0.02} />
      <OrbitingRing radius={4.2} color="#2A35E0" speed={-0.015} tilt={Math.PI * 0.4} />
      <OrbitingRing radius={5.0} color="#3A45E8" speed={0.01} tilt={Math.PI * 0.6} />
    </>
  );
}

export default function ThreeScene() {
  return (
    <Canvas
      camera={{ position: [0, 0, 9], fov: 55 }}
      dpr={[1, 2]}
      gl={{
        antialias: true,
        alpha: true,
        powerPreference: 'high-performance',
      }}
      className="!pointer-events-none"
    >
      <Scene />
    </Canvas>
  );
}
