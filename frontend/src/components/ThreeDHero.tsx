import React, { useRef, useMemo } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Float, MeshDistortMaterial, Trail } from "@react-three/drei";
import * as THREE from "three";

// ── Animated Core Orb (AI Shield) ──
const AICore: React.FC<{ mouseX: number; mouseY: number }> = ({ mouseX, mouseY }) => {
  const meshRef = useRef<THREE.Mesh>(null!);

  useFrame(({ clock }) => {
    if (meshRef.current) {
      meshRef.current.rotation.x = Math.sin(clock.getElapsedTime() * 0.3) * 0.1;
      meshRef.current.rotation.y = Math.sin(clock.getElapsedTime() * 0.2) * 0.1;
      // Mouse parallax
      meshRef.current.position.x = mouseX * 0.5;
      meshRef.current.position.y = -mouseY * 0.5;
    }
  });

  return (
    <Float speed={1.5} rotationIntensity={0.2} floatIntensity={0.5}>
      <mesh ref={meshRef} scale={1.8}>
        <dodecahedronGeometry args={[1, 0]} />
        <MeshDistortMaterial
          color="#4F7CFF"
          emissive="#7C5CFF"
          emissiveIntensity={0.3}
          roughness={0.2}
          metalness={0.8}
          distort={0.25}
          speed={2}
        />
      </mesh>
      {/* Inner glow sphere */}
      <mesh scale={0.6}>
        <sphereGeometry args={[1, 32, 32]} />
        <meshBasicMaterial color="#06B6D4" transparent opacity={0.3} />
      </mesh>
    </Float>
  );
};

// ── Orbital Node ──
const OrbitalNode: React.FC<{
  radius: number;
  speed: number;
  offset: number;
  color: string;
  size: number;
  mouseX: number;
  mouseY: number;
}> = ({ radius, speed, offset, color, size, mouseX, mouseY }) => {
  const ref = useRef<THREE.Mesh>(null!);
  const angle = useRef(offset);

  useFrame(({ clock }) => {
    angle.current += speed * 0.005;
    if (ref.current) {
      ref.current.position.x = Math.cos(angle.current + clock.getElapsedTime() * speed * 0.3) * radius + mouseX * 1.2;
      ref.current.position.z = Math.sin(angle.current + clock.getElapsedTime() * speed * 0.3) * radius + mouseY * 1.2;
      ref.current.position.y = Math.sin(angle.current * 0.7) * 0.5;
    }
  });

  return (
    <mesh ref={ref}>
      <sphereGeometry args={[size, 16, 16]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.6} />
    </mesh>
  );
};

// ── Connection Lines ──
const ConnectionLines: React.FC<{ mouseX: number; mouseY: number }> = ({ mouseX, mouseY }) => {
  const points = useMemo(() => {
    const pts = [];
    const numLines = 8;
    for (let i = 0; i < numLines; i++) {
      const angle = (i / numLines) * Math.PI * 2;
      const radius = 3.5;
      pts.push([
        new THREE.Vector3(Math.cos(angle) * radius, Math.sin(angle * 1.5) * 0.8, Math.sin(angle) * radius),
        new THREE.Vector3(0, 0, 0),
      ]);
    }
    return pts;
  }, []);

  const lineRef = useRef<THREE.Group>(null!);

  useFrame(({ clock }) => {
    if (lineRef.current) {
      lineRef.current.rotation.y = clock.getElapsedTime() * 0.05;
      lineRef.current.position.x = mouseX * 0.8;
      lineRef.current.position.y = -mouseY * 0.8;
    }
  });

  return (
    <group ref={lineRef}>
      {points.map(([start], idx) => (
        <Trail key={idx} width={0.8} length={4} color={new THREE.Color("#4F7CFF")} attenuation={(t) => t * t}>
          <mesh position={start}>
            <sphereGeometry args={[0.04, 8, 8]} />
            <meshBasicMaterial color="#4F7CFF" />
          </mesh>
        </Trail>
      ))}
    </group>
  );
};

// ── Particle Field ──
const ParticleField: React.FC = () => {
  const count = 200;
  const positions = useMemo(() => {
    const pos = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 20;
      pos[i * 3 + 1] = (Math.random() - 0.5) * 15;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 10;
    }
    return pos;
  }, []);

  const ref = useRef<THREE.Points>(null!);

  useFrame(({ clock }) => {
    if (ref.current) {
      ref.current.rotation.y = clock.getElapsedTime() * 0.02;
    }
  });

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={count}
          array={positions}
          itemSize={3}
          args={[positions, 3] as any}
        />
      </bufferGeometry>
      <pointsMaterial
        size={0.04}
        color="#4F7CFF"
        transparent
        opacity={0.6}
        sizeAttenuation
      />
    </points>
  );
};

// ── Security Shield Ring ──
const SecurityRing: React.FC = () => {
  const ref = useRef<THREE.Mesh>(null!);

  useFrame(({ clock }) => {
    if (ref.current) {
      ref.current.rotation.z = clock.getElapsedTime() * 0.1;
      ref.current.rotation.x = Math.sin(clock.getElapsedTime() * 0.2) * 0.1;
    }
  });

  return (
    <mesh ref={ref} position={[0, 0, -0.5]} scale={2.8}>
      <torusGeometry args={[1, 0.02, 16, 64]} />
      <meshStandardMaterial color="#4F7CFF" emissive="#4F7CFF" emissiveIntensity={0.3} transparent opacity={0.4} />
    </mesh>
  );
};

const SecondRing: React.FC = () => {
  const ref = useRef<THREE.Mesh>(null!);

  useFrame(({ clock }) => {
    if (ref.current) {
      ref.current.rotation.x = clock.getElapsedTime() * 0.08;
      ref.current.rotation.y = clock.getElapsedTime() * 0.12;
    }
  });

  return (
    <mesh ref={ref} position={[0, 0, 0.3]} scale={2.4}>
      <torusGeometry args={[1, 0.015, 16, 48]} />
      <meshStandardMaterial color="#7C5CFF" emissive="#7C5CFF" emissiveIntensity={0.2} transparent opacity={0.3} />
    </mesh>
  );
};

// ── Scene Container ──
const Scene3D: React.FC = () => {
  const [mouse, setMouse] = React.useState({ x: 0, y: 0 });

  React.useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      const x = (e.clientX / window.innerWidth - 0.5) * 2;
      const y = (e.clientY / window.innerHeight - 0.5) * 2;
      setMouse({ x, y });
    };
    window.addEventListener("mousemove", handleMouseMove);
    return () => window.removeEventListener("mousemove", handleMouseMove);
  }, []);

  return (
    <div className="absolute inset-0 -z-10">
      <Canvas
        camera={{ position: [0, 0, 6], fov: 50 }}
        dpr={[1, 2]}
        gl={{ antialias: true, alpha: true }}
      >
        <ambientLight intensity={0.4} />
        <directionalLight position={[5, 5, 5]} intensity={1} />
        <pointLight position={[-5, -5, -5]} intensity={0.5} color="#4F7CFF" />

        <AICore mouseX={mouse.x} mouseY={mouse.y} />

        {[
          { radius: 3.5, speed: 0.8, offset: 0, color: "#4F7CFF", size: 0.15 },
          { radius: 4.2, speed: -0.5, offset: 1.5, color: "#7C5CFF", size: 0.1 },
          { radius: 3.8, speed: 0.6, offset: 3, color: "#06B6D4", size: 0.12 },
          { radius: 4.5, speed: -0.4, offset: 4.5, color: "#22C55E", size: 0.08 },
          { radius: 4.8, speed: 0.7, offset: 6, color: "#F59E0B", size: 0.09 },
        ].map((node, idx) => (
          <OrbitalNode key={idx} {...node} mouseX={mouse.x} mouseY={mouse.y} />
        ))}

        <ConnectionLines mouseX={mouse.x} mouseY={mouse.y} />
        <ParticleField />
        <SecurityRing />
        <SecondRing />
      </Canvas>
    </div>
  );
};

export default Scene3D;
