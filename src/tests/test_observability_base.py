import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def load_observability_service_class():
    module_path = Path(__file__).resolve().parents[1] / "app/services/observability/base.py"
    spec = spec_from_file_location("observability_base", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {module_path}")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ObservabilityService


class ObservabilityServiceTest(unittest.TestCase):
    def test_create_trace_id_returns_unique_hex_identifiers(self) -> None:
        service = load_observability_service_class()()

        first_trace_id = service.create_trace_id()
        second_trace_id = service.create_trace_id()

        self.assertNotEqual(first_trace_id, second_trace_id)
        self.assertEqual(len(first_trace_id), 32)
        self.assertEqual(len(second_trace_id), 32)
        int(first_trace_id, 16)
        int(second_trace_id, 16)


if __name__ == "__main__":
    unittest.main()
