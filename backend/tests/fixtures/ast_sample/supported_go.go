package auth

import (
	"context"
	"fmt"
)

const MaxTokenTTL = 3600

type TokenValidator interface {
	Validate(ctx context.Context, token string) (bool, error)
}

type JWTService struct {
	secretKey string
}

func NewJWTService(secret string) *JWTService {
	return &JWTService{
		secretKey: secret,
	}
}

func (s *JWTService) VerifyToken(ctx context.Context, rawToken string) (bool, error) {
	if rawToken == "" {
		return false, fmt.Errorf("empty token")
	}
	return checkSignature(rawToken, s.secretKey), nil
}

func checkSignature(token string, secret string) bool {
	return len(token) > len(secret)
}
