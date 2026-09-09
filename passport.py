"""
Passport Machine Readable Zone (MRZ) validation, per ICAO 9303.

Why this is worth having
------------------------
Every other non-Aadhaar document in this system tops out at "no forgery
detected", because none of them carries anything to check against. A passport
is different: its MRZ has **check digits**, computed over the passport number,
the date of birth, the expiry date and the composite of all of them.

That makes this a STRUCTURAL check in the same class as the Verhoeff checksum
on an Aadhaar number — deterministic arithmetic, not a heuristic. Alter a digit
of the passport number or shift the date of birth on a scanned passport and,
unless the forger also recomputes four check digits correctly, the arithmetic
says so. That is a real, explainable catch.

What it still does NOT prove
----------------------------
The check digits are public arithmetic, not a signature. A competent forger
recomputes them, exactly as they can generate a Verhoeff-valid Aadhaar number
in a loop. A passing MRZ means "internally consistent", never "genuine".

The actual cryptographic anchor in a modern passport is the eMRTD chip, which
is signed by the issuing country and read over NFC. That is out of reach from a
photograph, so `UNVERIFIABLE` remains the ceiling for a passport image — which
is the honest answer and the one this project keeps giving.

Format
------
TD3 (the passport booklet) is two lines of 44 characters:

    line 1  P<ISSUER<<SURNAME<<GIVEN<NAMES<<<<<<<<<<<<<<
    line 2  NNNNNNNNNCIIIYYMMDDCSYYMMDDC<PERSONAL<<<<<CC

where C are check digits. TD1 (ID-card sized) is three lines of 30 and is
handled too, since several countries issue passport cards in that format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MRZ_OK = "MRZ_CHECKSUMS_OK"
MRZ_NOT_FOUND = "MRZ_NOT_FOUND"
MRZ_MALFORMED = "MRZ_MALFORMED"
MRZ_CHECK_FAILED = "MRZ_CHECK_DIGIT_FAILED"
MRZ_EXPIRED = "MRZ_DOCUMENT_EXPIRED"

# ICAO 9303 weighting, repeating across each field.
WEIGHTS = (7, 3, 1)

# The MRZ alphabet: digits, A-Z, and the filler character.
MRZ_LINE = re.compile(r"^[A-Z0-9<]+$")


@dataclass
class MRZResult:
    found: bool
    document_type: str | None = None
    issuing_state: str | None = None
    nationality: str | None = None
    surname: str | None = None
    given_names: str | None = None
    # Deliberately NOT returned in full to the API layer; see redacted().
    passport_number: str | None = None
    date_of_birth: str | None = None
    expiry_date: str | None = None
    sex: str | None = None
    checks: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def redacted(self) -> dict:
        """
        Safe to render. Same reasoning as the Aadhaar path: verification does
        not need to display who somebody is, so the identifying fields are
        reduced to a shape rather than passed through.
        """
        def mask(value: str | None) -> str | None:
            if not value:
                return value
            return value[0] + "*" * (len(value) - 1)

        return {
            "document_type": self.document_type,
            "issuing_state": self.issuing_state,
            "nationality": self.nationality,
            "surname": mask(self.surname),
            "given_names": mask(self.given_names),
            "passport_number": mask(self.passport_number),
            "date_of_birth": mask(self.date_of_birth),
            "expiry_date": self.expiry_date,  # coarse, and needed to show expiry
            "sex": self.sex,
            "checks": self.checks,
        }


def character_value(character: str) -> int:
    """Digits are themselves, letters are 10..35, filler is 0."""
    if character.isdigit():
        return int(character)
    if character == "<":
        return 0
    if "A" <= character <= "Z":
        return ord(character) - ord("A") + 10
    # Anything else is not MRZ alphabet; treat as filler rather than raising,
    # because OCR noise should degrade to a failed check, not a crash.
    return 0


def check_digit(field_value: str) -> int:
    """
    ICAO 9303 check digit: weight each character by 7, 3, 1 repeating, sum,
    take modulo 10.
    """
    total = 0
    for index, character in enumerate(field_value):
        total += character_value(character) * WEIGHTS[index % 3]
    return total % 10


def _verify(field_value: str, expected: str) -> bool:
    """A non-numeric expected digit is a failed check, not an exception."""
    if not expected.isdigit():
        return False
    return check_digit(field_value) == int(expected)


def find_mrz_lines(text: str) -> list[str]:
    """
    Pull candidate MRZ lines out of OCR text.

    OCR frequently reads the filler character '<' as 'K', '(' or '&', so lines
    are normalised before matching. Length is the strongest signal: 44 or 30
    characters of MRZ alphabet is not something body text produces.
    """
    candidates = []
    for raw in text.splitlines():
        line = raw.strip().upper().replace(" ", "")
        # Common OCR confusions for the filler character.
        line = line.replace("«", "<").replace("(", "<").replace("&", "<")
        if len(line) in (30, 36, 44) and MRZ_LINE.match(line):
            candidates.append(line)
    return candidates


def parse(text: str) -> MRZResult:
    """
    Parse and validate an MRZ out of OCR'd text.

    Returns found=False rather than guessing when no MRZ-shaped line is
    present — a passport photographed without its MRZ in frame is a capture
    problem, not a forgery, and must not be reported as one.
    """
    lines = find_mrz_lines(text)
    if len(lines) < 2:
        return MRZResult(found=False, reasons=[MRZ_NOT_FOUND])

    # TD3: two lines of 44. Prefer the last two, since headers and other text
    # occasionally match the length filter.
    td3 = [line for line in lines if len(line) == 44]
    if len(td3) >= 2:
        return _parse_td3(td3[-2], td3[-1])

    td1 = [line for line in lines if len(line) == 30]
    if len(td1) >= 3:
        return _parse_td1(td1[-3], td1[-2], td1[-1])

    return MRZResult(found=False, reasons=[MRZ_MALFORMED])


def _split_names(field_value: str) -> tuple[str, str]:
    surname, _, given = field_value.partition("<<")
    return (surname.replace("<", " ").strip(),
            given.replace("<", " ").strip())


def _parse_td3(line1: str, line2: str) -> MRZResult:
    surname, given = _split_names(line1[5:44])

    number = line2[0:9]
    number_check = line2[9]
    nationality = line2[10:13]
    birth = line2[13:19]
    birth_check = line2[19]
    sex = line2[20]
    expiry = line2[21:27]
    expiry_check = line2[27]
    personal = line2[28:42]
    personal_check = line2[42]
    composite_check = line2[43]

    # The composite runs over the number, DOB and expiry fields *including*
    # their own check digits, plus the optional personal-number field.
    composite_source = (
        line2[0:10] + line2[13:20] + line2[21:28] + personal + personal_check
    )

    checks = {
        "passport_number": _verify(number, number_check),
        "date_of_birth": _verify(birth, birth_check),
        "expiry_date": _verify(expiry, expiry_check),
        "composite": _verify(composite_source, composite_check),
    }

    return _finalise(
        document_type=line1[0:2].replace("<", ""),
        issuing_state=line1[2:5].replace("<", ""),
        nationality=nationality.replace("<", ""),
        surname=surname, given=given,
        number=number.replace("<", ""),
        birth=birth, expiry=expiry, sex=sex.replace("<", ""),
        checks=checks,
    )


def _parse_td1(line1: str, line2: str, line3: str) -> MRZResult:
    number = line1[5:14]
    number_check = line1[14]

    birth = line2[0:6]
    birth_check = line2[6]
    sex = line2[7]
    expiry = line2[8:14]
    expiry_check = line2[14]
    nationality = line2[15:18]
    composite_check = line2[29]

    composite_source = line1[5:30] + line2[0:7] + line2[8:15] + line2[18:29]
    surname, given = _split_names(line3)

    checks = {
        "passport_number": _verify(number, number_check),
        "date_of_birth": _verify(birth, birth_check),
        "expiry_date": _verify(expiry, expiry_check),
        "composite": _verify(composite_source, composite_check),
    }

    return _finalise(
        document_type=line1[0:2].replace("<", ""),
        issuing_state=line1[2:5].replace("<", ""),
        nationality=nationality.replace("<", ""),
        surname=surname, given=given,
        number=number.replace("<", ""),
        birth=birth, expiry=expiry, sex=sex.replace("<", ""),
        checks=checks,
    )


def _finalise(*, document_type, issuing_state, nationality, surname, given,
              number, birth, expiry, sex, checks) -> MRZResult:
    reasons: list[str] = []
    if all(checks.values()):
        reasons.append(MRZ_OK)
    else:
        reasons.append(MRZ_CHECK_FAILED)

    if _is_expired(expiry):
        # Expiry is a fact about the document, not an accusation about the
        # holder, and it is reported separately from the checksum result.
        reasons.append(MRZ_EXPIRED)

    return MRZResult(
        found=True,
        document_type=document_type or None,
        issuing_state=issuing_state or None,
        nationality=nationality or None,
        surname=surname or None,
        given_names=given or None,
        passport_number=number or None,
        date_of_birth=birth or None,
        expiry_date=expiry or None,
        sex=sex or None,
        checks=checks,
        reasons=reasons,
    )


def _is_expired(expiry: str) -> bool:
    """
    YYMMDD, with the usual two-digit-year problem.

    ICAO does not carry a century. The convention used here is the common one:
    an expiry year is read as 20YY, because a document that expired more than
    a few decades ago is not something anyone presents for verification.
    """
    from datetime import date

    if len(expiry) != 6 or not expiry.isdigit():
        return False
    year = 2000 + int(expiry[0:2])
    month, day = int(expiry[2:4]), int(expiry[4:6])
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return False
    try:
        return date(year, month, day) < date.today()
    except ValueError:
        return False
