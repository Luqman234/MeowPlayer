import math
from dataclasses import dataclass


MATH_ROLL_INTERVAL = 60.0
MATH_EVENT_CHANCE = 0.20
QUANTUM_EXAM_SECONDS = 300.0


@dataclass(frozen=True)
class MathQuestion:
    difficulty: str
    label: str
    prompt: str
    answer: str
    tolerance: float = 0.0


DIFFICULTY_WEIGHTS = (
    ("easy", 0.50),
    ("medium", 0.30),
    ("hard", 0.19),
    ("stochastic", 0.005),
    ("imo-p6", 0.005),
)


QUESTION_BANK = {
    "easy": (
        MathQuestion("easy", "EASY", "17 * 8 - 23 = ?", "113"),
        MathQuestion("easy", "EASY", "What is 14 * 7?", "98"),
        MathQuestion("easy", "EASY", "What is 3^4 + 19?", "100"),
        MathQuestion("easy", "EASY", "Solve 5x + 7 = 42. Enter x.", "7"),
    ),
    "medium": (
        MathQuestion(
            "medium",
            "MEDIUM",
            "Solve x^2 - 9x + 20 = 0. Enter the smaller root.",
            "4",
        ),
        MathQuestion(
            "medium",
            "MEDIUM",
            "If 3x + 2y = 19 and x - y = 3, enter x.",
            "5",
        ),
        MathQuestion(
            "medium",
            "MEDIUM",
            "A geometric sequence starts 3, 6, 12, ... Enter term 10.",
            "1536",
        ),
        MathQuestion(
            "medium",
            "MEDIUM",
            "Evaluate sum_{k=1}^{20} k. Enter the integer.",
            "210",
        ),
    ),
    "hard": (
        MathQuestion(
            "hard",
            "HARD",
            "How many positive divisors does 2^6 * 3^4 * 5^2 have?",
            "105",
        ),
        MathQuestion(
            "hard",
            "HARD",
            "Evaluate integral_0^1 12x^2(1-x) dx.",
            "1",
            tolerance=1e-9,
        ),
        MathQuestion(
            "hard",
            "HARD",
            "Find the least positive n with n = 2 (mod 7), "
            "n = 3 (mod 8), n = 4 (mod 9).",
            "499",
        ),
        MathQuestion(
            "hard",
            "HARD",
            "How many onto functions exist from a 5-element set "
            "to a 3-element set?",
            "150",
        ),
    ),
    "stochastic": (
        MathQuestion(
            "stochastic",
            "STOCHASTIC CALCULUS",
            "For standard Brownian motion W_t, Ito's lemma applied to "
            "f(x)=x^4 gives a dt term c*W_t^2 dt. Enter c.",
            "6",
        ),
        MathQuestion(
            "stochastic",
            "STOCHASTIC CALCULUS",
            "For dX_t = 2 dW_t and X_0=0, enter Var[X_3].",
            "12",
        ),
    ),
    "imo-p6": (
        MathQuestion(
            "imo-p6",
            "IMO P6-STYLE BOSS",
            "Positive integers a,b satisfy (ab+1) | (a^2+b^2). "
            "For a=3 and b>3, find the least b for which the quotient "
            "is a perfect square. Enter b only.",
            "27",
        ),
    ),
}


SKIP_PENALTIES = {
    "easy": {
        "malice": 3,
        "rewind": (5.0, 10.0),
        "speed": None,
        "speed_seconds": 0.0,
        "restart": False,
        "random_track": False,
    },
    "medium": {
        "malice": 6,
        "rewind": (10.0, 20.0),
        "speed": 0.95,
        "speed_seconds": 10.0,
        "restart": False,
        "random_track": False,
    },
    "hard": {
        "malice": 10,
        "rewind": (20.0, 35.0),
        "speed": 0.90,
        "speed_seconds": 15.0,
        "restart": False,
        "random_track": False,
    },
    "stochastic": {
        "malice": 18,
        "rewind": None,
        "speed": 0.85,
        "speed_seconds": 20.0,
        "restart": True,
        "random_track": False,
    },
    "imo-p6": {
        "malice": 25,
        "rewind": None,
        "speed": 0.82,
        "speed_seconds": 15.0,
        "restart": True,
        "random_track": True,
    },
    "quantum": {
        "malice": 35,
        "rewind": (30.0, 45.0),
        "speed": 0.80,
        "speed_seconds": 25.0,
        "restart": True,
        "random_track": True,
    },
}


QUANTUM_FINAL_EXAM = r"""Extremely Hard Quantum Physics Problem — Three-Qubit Dynamics

Consider three distinguishable spin-1/2 particles A,B,C, initially prepared in

|psi(0)> = N ( |000> + lambda|111> + mu|001> + mu|010> + mu|100> ),

where lambda,mu are complex and N>0 is the normalization constant.

The system evolves under

H = J( sigma_x^A sigma_x^B + sigma_x^B sigma_x^C + sigma_x^C sigma_x^A )
  + Delta( sigma_z^A sigma_z^B + sigma_z^B sigma_z^C + sigma_z^C sigma_z^A )
  + B sum_{k=A,B,C} sigma_z^k,

with real J, Delta, B and hbar=1. Do not assume any parameter is small.

1. Find exact N and construct the full 8x8 matrix of H in the computational
   basis {|000>,|001>,...,|111>}.

2. Exploit every symmetry of H to block-diagonalize it. Determine all
   eigenvalues and an orthonormal eigenbasis analytically.

3. Obtain an exact closed-form expression for
   |psi(t)> = exp(-iHt)|psi(0)>.

4. Compute rho_AB(t) = Tr_C(|psi(t)><psi(t)|).

5. Calculate the eigenvalues of rho_AB^(T_B)(t) and derive the exact
   entanglement negativity
   N_AB(t) = (||rho_AB^(T_B)(t)||_1 - 1)/2.

6. For |psi(t)> = sum a_ijk(t)|ijk>, calculate the Cayley hyperdeterminant
   and hence tau_3(t)=4|Det(a(t))|, using

   Det(a) =
   a000^2 a111^2 + a001^2 a110^2 + a010^2 a101^2 + a100^2 a011^2
   - 2( a000 a001 a110 a111 + a000 a010 a101 a111
      + a000 a100 a011 a111 + a001 a010 a101 a110
      + a001 a100 a011 a110 + a010 a100 a011 a101 )
   + 4( a000 a011 a101 a110 + a111 a100 a010 a001 ).

7. Determine all (lambda,mu) for which the initial state belongs to the
   GHZ, W, biseparable, and fully separable genuine SLOCC classes.

8. Prove or disprove:
   [The Hamiltonian can dynamically convert an initially W-class state
    into a GHZ-class state.]
   If it can, determine conditions on J, Delta, B, mu and the earliest t>0
   for which tau_3(t)>0.

9. Finally impose lambda=0, mu=1/sqrt(3), B=0, Delta=J. Determine whether
   there is finite t_*>0 for which
   rho_A(t_*) = rho_B(t_*) = rho_C(t_*) = I_2/2
   and simultaneously tau_3(t_*)=1.
   If so, find the smallest J t_*. If not, prove impossibility rigorously.
"""


def select_math_difficulty(value):
    value = min(1.0, max(0.0, float(value)))
    cumulative = 0.0
    for difficulty, weight in DIFFICULTY_WEIGHTS:
        cumulative += weight
        if value < cumulative:
            return difficulty
    return "imo-p6"


def generate_math_question(rng):
    difficulty = select_math_difficulty(rng.random())
    return rng.choice(QUESTION_BANK[difficulty])


def answer_is_correct(question, answer):
    answer = str(answer).strip()
    if not answer:
        return False

    expected = str(question.answer).strip()

    if question.tolerance > 0:
        try:
            return math.isclose(
                float(answer),
                float(expected),
                rel_tol=0.0,
                abs_tol=question.tolerance,
            )
        except ValueError:
            return False

    try:
        return float(answer) == float(expected)
    except ValueError:
        return answer.casefold() == expected.casefold()


def surrender_multiplier(surrender_count):
    count = max(0, int(surrender_count))
    if count <= 1:
        return 1.0
    if count == 2:
        return 1.15
    if count == 3:
        return 1.30
    return 1.50


def skip_penalty(difficulty, surrender_count=1):
    base = SKIP_PENALTIES[difficulty]
    multiplier = surrender_multiplier(surrender_count)
    penalty = dict(base)
    penalty["multiplier"] = multiplier
    penalty["malice"] = int(round(base["malice"] * multiplier))

    if base["rewind"] is not None:
        penalty["rewind"] = (
            base["rewind"][0] * multiplier,
            base["rewind"][1] * multiplier,
        )

    return penalty
