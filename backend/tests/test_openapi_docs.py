"""Regression checks for the Chinese OpenAPI contract."""

from __future__ import annotations

import re

from app.main import create_app


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
GENERATED_VALIDATION_SCHEMAS = {"HTTPValidationError", "ValidationError"}


def _contains_chinese(value: str | None) -> bool:
    return bool(value and re.search(r"[\u4e00-\u9fff]", value))


def test_openapi_operations_have_chinese_documentation() -> None:
    schema = create_app().openapi()

    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            location = f"{method.upper()} {path}"
            assert _contains_chinese(operation.get("summary")), f"{location} 缺少中文 summary"
            assert _contains_chinese(operation.get("description")), f"{location} 缺少中文 description"

            success_response = next(
                (response for code, response in operation["responses"].items() if code.startswith("2")),
                None,
            )
            assert success_response is not None, f"{location} 缺少成功响应定义"
            assert _contains_chinese(success_response.get("description")), f"{location} 缺少中文响应说明"

            for parameter in operation.get("parameters", []):
                assert _contains_chinese(parameter.get("description")), (
                    f"{location} 的参数 {parameter['name']} 缺少中文说明"
                )

            request_body = operation.get("requestBody")
            if request_body:
                json_schema = request_body.get("content", {}).get("application/json", {}).get("schema", {})
                body_description = request_body.get("description") or json_schema.get("description")
                assert _contains_chinese(body_description), f"{location} 缺少中文请求体说明"


def test_openapi_request_models_have_chinese_field_descriptions() -> None:
    schema = create_app().openapi()

    for name, model_schema in schema["components"]["schemas"].items():
        if name in GENERATED_VALIDATION_SCHEMAS:
            continue
        for field_name, field_schema in model_schema.get("properties", {}).items():
            assert _contains_chinese(field_schema.get("description")), (
                f"OpenAPI 模型 {name}.{field_name} 缺少中文字段说明"
            )


def test_openapi_tags_and_bearer_auth_are_documented_in_chinese() -> None:
    schema = create_app().openapi()

    for tag in schema["tags"]:
        assert _contains_chinese(tag.get("description")), f"标签 {tag['name']} 缺少中文说明"

    bearer = schema["components"]["securitySchemes"]["HTTPBearer"]
    assert bearer["scheme"] == "bearer"
    assert _contains_chinese(bearer.get("description"))
