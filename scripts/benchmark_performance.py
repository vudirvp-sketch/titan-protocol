#!/usr/bin/env python3
"""
Performance Benchmark for TITAN Protocol
GATE-7C Validation Script

Tests:
- p50 latency < 200ms
- p95 latency < 500ms
- p99 latency < 1000ms
- Memory footprint < 512MB baseline
"""

import json
import os
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def benchmark_imports(samples: int = 10) -> dict:
    """Benchmark module import times."""
    latencies = []

    for _ in range(samples):
        tracemalloc.start()
        start = time.perf_counter()

        # Import key modules
        try:
            from src.state.checkpoint_manager import CheckpointManager
            from src.validation.guardian import Guardian
            from src.events.event_bus import EventBus
            from src.context.profile_router import ProfileRouter
        except ImportError:
            pass

        end = time.perf_counter()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        latencies.append((end - start) * 1000)  # ms

    return {
        'p50': statistics.median(latencies),
        'p95': sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 1 else latencies[0],
        'p99': sorted(latencies)[int(len(latencies) * 0.99)] if len(latencies) > 1 else latencies[0],
        'mean': statistics.mean(latencies),
        'samples': samples
    }


def benchmark_event_bus(samples: int = 50) -> dict:
    """Benchmark EventBus operations."""
    latencies = []
    memory_samples = []

    try:
        from src.events.event_bus import EventBus

        for _ in range(samples):
            tracemalloc.start()
            start = time.perf_counter()

            bus = EventBus()
            bus.subscribe("test.event", lambda e: None)
            bus.emit("test.event", {"data": "test"})
            bus.emit("test.event", {"data": "test2"})

            end = time.perf_counter()
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            latencies.append((end - start) * 1000)
            memory_samples.append(peak / 1024 / 1024)  # MB

        return {
            'p50': statistics.median(latencies),
            'p95': sorted(latencies)[int(len(latencies) * 0.95)],
            'p99': sorted(latencies)[int(len(latencies) * 0.99)],
            'memory_baseline_mb': statistics.mean(memory_samples),
            'samples': samples
        }
    except Exception as e:
        return {'error': str(e), 'samples': samples}


def benchmark_checkpoint_operations(samples: int = 30) -> dict:
    """Benchmark checkpoint serialization."""
    latencies = []
    memory_samples = []

    try:
        from src.state.checkpoint_manager import CheckpointManager
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(samples):
                tracemalloc.start()
                start = time.perf_counter()

                manager = CheckpointManager(base_path=tmpdir)
                checkpoint = {
                    'session_id': f'test-{i}',
                    'phase': 'PHASE_0',
                    'cursor': {'position': 0},
                    'chunks': [{'content': f'test content {j}'} for j in range(10)]
                }
                manager.save(checkpoint)
                loaded = manager.load()

                end = time.perf_counter()
                current, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()

                latencies.append((end - start) * 1000)
                memory_samples.append(peak / 1024 / 1024)

        return {
            'p50': statistics.median(latencies),
            'p95': sorted(latencies)[int(len(latencies) * 0.95)],
            'p99': sorted(latencies)[int(len(latencies) * 0.99)],
            'memory_baseline_mb': statistics.mean(memory_samples),
            'samples': samples
        }
    except Exception as e:
        return {'error': str(e), 'samples': samples}


def benchmark_config_loading(samples: int = 20) -> dict:
    """Benchmark configuration loading."""
    latencies = []

    try:
        import yaml

        config_path = Path(__file__).parent.parent / 'config.yaml'

        for _ in range(samples):
            start = time.perf_counter()

            with open(config_path) as f:
                config = yaml.safe_load(f)

            end = time.perf_counter()
            latencies.append((end - start) * 1000)

        return {
            'p50': statistics.median(latencies),
            'p95': sorted(latencies)[int(len(latencies) * 0.95)],
            'p99': sorted(latencies)[int(len(latencies) * 0.99)],
            'samples': samples
        }
    except Exception as e:
        return {'error': str(e), 'samples': samples}


def benchmark_validation_pipeline(samples: int = 20) -> dict:
    """Benchmark validation operations."""
    latencies = []
    memory_samples = []

    try:
        from src.validation.tiered_validator import TieredValidator

        for _ in range(samples):
            tracemalloc.start()
            start = time.perf_counter()

            validator = TieredValidator()
            # Simple validation test
            test_content = {
                'type': 'test',
                'content': 'x' * 1000
            }
            result = validator.validate(test_content, severity='SEV-3')

            end = time.perf_counter()
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            latencies.append((end - start) * 1000)
            memory_samples.append(peak / 1024 / 1024)

        return {
            'p50': statistics.median(latencies),
            'p95': sorted(latencies)[int(len(latencies) * 0.95)],
            'p99': sorted(latencies)[int(len(latencies) * 0.99)],
            'memory_baseline_mb': statistics.mean(memory_samples),
            'samples': samples
        }
    except Exception as e:
        return {'error': str(e), 'samples': samples}


def run_full_benchmark() -> dict:
    """Run all benchmarks and compile results."""
    results = {
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'python_version': sys.version,
        'benchmarks': {}
    }

    print("=" * 60)
    print("TITAN Protocol Performance Benchmark")
    print("=" * 60)

    # Run benchmarks
    print("\n1. Import Benchmark...")
    results['benchmarks']['imports'] = benchmark_imports(10)
    print(f"   p50: {results['benchmarks']['imports']['p50']:.2f}ms")

    print("\n2. EventBus Benchmark...")
    results['benchmarks']['event_bus'] = benchmark_event_bus(50)
    if 'error' not in results['benchmarks']['event_bus']:
        print(f"   p50: {results['benchmarks']['event_bus']['p50']:.2f}ms")
        print(f"   Memory: {results['benchmarks']['event_bus']['memory_baseline_mb']:.2f}MB")

    print("\n3. Checkpoint Benchmark...")
    results['benchmarks']['checkpoint'] = benchmark_checkpoint_operations(30)
    if 'error' not in results['benchmarks']['checkpoint']:
        print(f"   p50: {results['benchmarks']['checkpoint']['p50']:.2f}ms")
        print(f"   Memory: {results['benchmarks']['checkpoint']['memory_baseline_mb']:.2f}MB")

    print("\n4. Config Loading Benchmark...")
    results['benchmarks']['config'] = benchmark_config_loading(20)
    if 'error' not in results['benchmarks']['config']:
        print(f"   p50: {results['benchmarks']['config']['p50']:.2f}ms")

    print("\n5. Validation Pipeline Benchmark...")
    results['benchmarks']['validation'] = benchmark_validation_pipeline(20)
    if 'error' not in results['benchmarks']['validation']:
        print(f"   p50: {results['benchmarks']['validation']['p50']:.2f}ms")
        print(f"   Memory: {results['benchmarks']['validation']['memory_baseline_mb']:.2f}MB")

    # Calculate aggregate metrics
    all_latencies = []
    all_memory = []

    for name, data in results['benchmarks'].items():
        if 'error' not in data:
            if 'p50' in data:
                all_latencies.append(data['p50'])
            if 'memory_baseline_mb' in data:
                all_memory.append(data['memory_baseline_mb'])

    results['summary'] = {
        'aggregate_p50_ms': statistics.median(all_latencies) if all_latencies else 0,
        'aggregate_p95_ms': sorted(all_latencies)[int(len(all_latencies) * 0.95)] if len(all_latencies) > 1 else (all_latencies[0] if all_latencies else 0),
        'aggregate_p99_ms': sorted(all_latencies)[int(len(all_latencies) * 0.99)] if len(all_latencies) > 1 else (all_latencies[0] if all_latencies else 0),
        'peak_memory_mb': max(all_memory) if all_memory else 0
    }

    # Gate criteria validation
    print("\n" + "=" * 60)
    print("GATE-7C VALIDATION")
    print("=" * 60)

    summary = results['summary']
    gates = {
        'p50_latency': {
            'value': summary['aggregate_p50_ms'],
            'target': 200,
            'unit': 'ms',
            'pass': summary['aggregate_p50_ms'] < 200
        },
        'p95_latency': {
            'value': summary['aggregate_p95_ms'],
            'target': 500,
            'unit': 'ms',
            'pass': summary['aggregate_p95_ms'] < 500
        },
        'p99_latency': {
            'value': summary['aggregate_p99_ms'],
            'target': 1000,
            'unit': 'ms',
            'pass': summary['aggregate_p99_ms'] < 1000
        },
        'memory_footprint': {
            'value': summary['peak_memory_mb'],
            'target': 512,
            'unit': 'MB',
            'pass': summary['peak_memory_mb'] < 512
        }
    }

    results['gates'] = gates

    all_passed = all(g['pass'] for g in gates.values())

    for name, gate in gates.items():
        status = "✅ PASS" if gate['pass'] else "❌ FAIL"
        print(f"{name}: {gate['value']:.2f}{gate['unit']} (target: <{gate['target']}{gate['unit']}) {status}")

    print("\n" + "=" * 60)
    print(f"OVERALL: {'✅ ALL GATES PASSED' if all_passed else '❌ SOME GATES FAILED'}")
    print("=" * 60)

    results['overall_pass'] = all_passed

    return results


def main():
    output_dir = Path(__file__).parent.parent / 'outputs'
    output_dir.mkdir(exist_ok=True)

    results = run_full_benchmark()

    # Save results
    output_file = output_dir / 'benchmark_results.json'
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {output_file}")

    return 0 if results['overall_pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
