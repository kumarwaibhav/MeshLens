"""Compact convolutional bottleneck; every parameter is trained from scratch."""

from pathlib import Path
import hashlib
import io
import math
import pickle
import torch
from torch import nn
from torch.nn import functional as F


class ConvAutoencoder(nn.Module):
    def __init__(self, latent_channels: int = 8):
        super().__init__()
        if latent_channels not in {4, 8, 12, 16}:
            raise ValueError("Supported latent channel counts: 4,8,12,16")
        self.latent_channels = latent_channels
        self.encoder = nn.Sequential(
            nn.Conv2d(3, 12, 3, padding=1),
            nn.LeakyReLU(0.1),
            nn.Conv2d(12, 16, 4, stride=2, padding=1),
            nn.LeakyReLU(0.1),
            nn.Conv2d(16, 24, 4, stride=2, padding=1),
            nn.LeakyReLU(0.1),
            nn.Conv2d(24, latent_channels, 4, stride=2, padding=1),
        )
        self.decoder = nn.Sequential(
            nn.ConvTranspose2d(latent_channels, 24, 4, stride=2, padding=1),
            nn.LeakyReLU(0.1),
            nn.ConvTranspose2d(24, 16, 4, stride=2, padding=1),
            nn.LeakyReLU(0.1),
            nn.ConvTranspose2d(16, 12, 4, stride=2, padding=1),
            nn.LeakyReLU(0.1),
            nn.Conv2d(12, 3, 3, padding=1),
            nn.Sigmoid(),
        )

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        padded = F.pad(image, (16, 16, 16, 16), mode="reflect")
        rebuilt = self.decoder(self.encoder(padded))
        return rebuilt[:, :, 16:-16, 16:-16]


def validate_state_dict(state: dict, model: ConvAutoencoder) -> None:
    """Reject poisoned or incompatible weights before inference/training."""
    expected = model.state_dict()
    if not isinstance(state, dict) or set(state) != set(expected):
        raise ValueError("Checkpoint parameter names do not match the autoencoder")
    for name, tensor in state.items():
        if (
            not isinstance(tensor, torch.Tensor)
            or tensor.shape != expected[name].shape
            or tensor.dtype != expected[name].dtype
            or not torch.isfinite(tensor).all()
        ):
            raise ValueError(f"Invalid checkpoint parameter: {name}")


def load_checkpoint(
    path: Path, expected_sha256: str | None = None
) -> tuple[ConvAutoencoder, dict]:
    try:
        content = Path(path).read_bytes()
        if (
            expected_sha256 is not None
            and hashlib.sha256(content).hexdigest() != expected_sha256
        ):
            raise ValueError(
                "Checkpoint SHA256 mismatch; restore the matching frozen artifact"
            )
        checkpoint = torch.load(
            io.BytesIO(content), map_location="cpu", weights_only=True
        )
        config = checkpoint["config"]
        if (
            not isinstance(config, dict)
            or type(config.get("latent_channels")) is not int
        ):
            raise ValueError("Invalid checkpoint architecture configuration")
        model = ConvAutoencoder(latent_channels=config["latent_channels"])
        for name in ("epochs", "best_epoch", "parameters", "image_size", "patch_size"):
            if name in config and (type(config[name]) is not int or config[name] <= 0):
                raise ValueError(f"Invalid checkpoint configuration: {name}")
        if "best_tune_mse" in config and (
            not math.isfinite(config["best_tune_mse"]) or config["best_tune_mse"] < 0
        ):
            raise ValueError("Invalid checkpoint development error")
        if "noise_std" in config and (
            type(config["noise_std"]) not in (int, float)
            or not math.isfinite(config["noise_std"])
            or not 0 <= config["noise_std"] <= 1
        ):
            raise ValueError("Invalid checkpoint training noise")
        if config.get("image_size", 256) != 256 or config.get("patch_size", 64) != 64:
            raise ValueError("Unsupported checkpoint image/patch dimensions")
        if "best_epoch" in config and not 1 <= config["best_epoch"] <= config["epochs"]:
            raise ValueError("Invalid checkpoint best epoch")
        if "parameters" in config and config["parameters"] != sum(
            p.numel() for p in model.parameters()
        ):
            raise ValueError("Checkpoint parameter count disagrees with architecture")
        validate_state_dict(checkpoint["state_dict"], model)
        model.load_state_dict(checkpoint["state_dict"])
    except (
        OSError,
        KeyError,
        TypeError,
        RuntimeError,
        EOFError,
        IndexError,
        pickle.UnpicklingError,
    ) as error:
        raise ValueError(f"Cannot load a valid checkpoint: {path}") from error
    model.eval()
    return model, config
