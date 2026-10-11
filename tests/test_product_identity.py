from code_visualizer.config import PRODUCT


def test_product_identity_is_centralized() -> None:
    assert PRODUCT.name == "Code Visualizer"
    assert PRODUCT.application_id == "org.codevisualizer.studio"
    assert PRODUCT.project_format_revision == 11
