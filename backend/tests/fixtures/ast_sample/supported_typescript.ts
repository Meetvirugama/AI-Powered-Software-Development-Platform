import { Observable } from 'rxjs';
import { Helper } from './local_module';

export const API_VERSION = "v2";

export interface UserProfile {
    id: string;
    username: string;
    isActive: boolean;
}

export class ProfileService {
    private serviceName: string = "ProfileService";

    public getUserProfile(userId: string): UserProfile {
        return {
            id: userId,
            username: "testuser",
            isActive: true,
        };
    }
}

export function validateProfile(profile: UserProfile): boolean {
    return profile.username.length > 0;
}
