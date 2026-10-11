"""Typed edits of project-authored language definitions through the existing authority."""

from dataclasses import dataclass

from code_visualizer.application.commands import Operation
from code_visualizer.domain.language import (
    AuthoredDomainLanguage,
    AuthoredTransformation,
    ValidatorDefinition,
)
from code_visualizer.domain.notation import NotationDefinition
from code_visualizer.persistence.language import authored_language_to_data, language_record_to_data


@dataclass(frozen=True, slots=True)
class PutDomainLanguage:
    language: AuthoredDomainLanguage

    def to_operation(self) -> Operation:
        return Operation(
            "domain.language.put", {"language": authored_language_to_data(self.language)}
        )


@dataclass(frozen=True, slots=True)
class DeleteDomainLanguage:
    language_id: str

    def to_operation(self) -> Operation:
        return Operation("domain.language.delete", {"language_id": self.language_id})


@dataclass(frozen=True, slots=True)
class PutDomainNotation:
    language_id: str
    definition: NotationDefinition

    def to_operation(self) -> Operation:
        return Operation(
            "domain.language.notation.put",
            {
                "language_id": self.language_id,
                "definition": language_record_to_data(self.definition),
            },
        )


@dataclass(frozen=True, slots=True)
class DeleteDomainNotation:
    language_id: str
    definition_id: str

    def to_operation(self) -> Operation:
        return Operation(
            "domain.language.notation.delete",
            {
                "language_id": self.language_id,
                "definition_id": self.definition_id,
            },
        )


@dataclass(frozen=True, slots=True)
class PutDomainValidator:
    language_id: str
    definition: ValidatorDefinition

    def to_operation(self) -> Operation:
        return Operation(
            "domain.language.validator.put",
            {
                "language_id": self.language_id,
                "definition": language_record_to_data(self.definition),
            },
        )


@dataclass(frozen=True, slots=True)
class DeleteDomainValidator:
    language_id: str
    definition_id: str

    def to_operation(self) -> Operation:
        return Operation(
            "domain.language.validator.delete",
            {
                "language_id": self.language_id,
                "definition_id": self.definition_id,
            },
        )


@dataclass(frozen=True, slots=True)
class PutDomainTransformation:
    language_id: str
    definition: AuthoredTransformation

    def to_operation(self) -> Operation:
        return Operation(
            "domain.language.transformation.put",
            {
                "language_id": self.language_id,
                "definition": language_record_to_data(self.definition),
            },
        )


@dataclass(frozen=True, slots=True)
class DeleteDomainTransformation:
    language_id: str
    definition_id: str

    def to_operation(self) -> Operation:
        return Operation(
            "domain.language.transformation.delete",
            {
                "language_id": self.language_id,
                "definition_id": self.definition_id,
            },
        )
