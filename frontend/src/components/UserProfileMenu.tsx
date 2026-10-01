import { useState, useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { User, LogOut, ChevronDown, ShieldCheck, Sparkles } from 'lucide-react'
import { api } from '../services/api'
import type { UserProfile } from '../types/api'

function getInitials(name?: string | null, email?: string | null): string {
  if (name && name.trim()) {
    const parts = name.trim().split(/\s+/)
    if (parts.length >= 2) {
      return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
    }
    return parts[0].slice(0, 2).toUpperCase()
  }
  if (email && email.trim()) {
    const userPart = email.split('@')[0]
    return userPart.slice(0, 2).toUpperCase()
  }
  return 'U'
}

export function UserProfileMenu() {
  const [isOpen, setIsOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  const { data: profile, isLoading } = useQuery<UserProfile>({
    queryKey: ['user-profile'],
    queryFn: api.me,
    staleTime: 10 * 60 * 1000,
    retry: false,
  })

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isOpen])

  // Close on Escape
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setIsOpen(false)
    }
    if (isOpen) {
      window.addEventListener('keydown', handleKeyDown)
    }
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen])

  const handleSignOut = () => {
    window.location.href = '/.auth/logout?post_logout_redirect_uri=/'
  }

  if (isLoading) {
    return <div className="userProfileSkeleton" />
  }

  const isAuthenticated = Boolean(profile?.authenticated)
  const displayName = profile?.name || profile?.email?.split('@')[0] || (isAuthenticated ? 'Signed In' : 'Local User')
  const email = profile?.email || ''
  const initials = getInitials(profile?.name, profile?.email)
  const provider = profile?.provider || 'Microsoft Entra ID'

  return (
    <div className="userProfileContainer" ref={menuRef}>
      <button
        type="button"
        className={`userProfileTrigger ${isOpen ? 'active' : ''}`}
        onClick={() => setIsOpen(prev => !prev)}
        aria-haspopup="true"
        aria-expanded={isOpen}
        title={isAuthenticated ? `Signed in as ${displayName}` : 'User session info'}
      >
        <div className={`userAvatar ${isAuthenticated ? 'online' : 'dev'}`}>
          {isAuthenticated ? initials : <User size={13} />}
        </div>
        <span className="userProfileName">{displayName}</span>
        <ChevronDown size={13} className={`userProfileChevron ${isOpen ? 'rotate' : ''}`} />
      </button>

      {isOpen && (
        <div className="userProfileDropdown" role="menu">
          <div className="userDropdownHeader">
            <div className={`userDropdownAvatar ${isAuthenticated ? 'online' : 'dev'}`}>
              {isAuthenticated ? initials : <User size={20} />}
            </div>
            <div className="userDropdownMeta">
              <span className="userDropdownDisplayName">{profile?.name || displayName}</span>
              {email && <span className="userDropdownEmail">{email}</span>}
              <div className="userDropdownBadge">
                {isAuthenticated ? (
                  <>
                    <ShieldCheck size={11} color="#34d399" />
                    <span>{provider}</span>
                  </>
                ) : (
                  <>
                    <Sparkles size={11} color="#a5b4fc" />
                    <span>Local Development</span>
                  </>
                )}
              </div>
            </div>
          </div>

          <div className="userDropdownDivider" />

          {isAuthenticated ? (
            <div className="userDropdownActions">
              <button
                type="button"
                className="userSignOutBtn"
                onClick={handleSignOut}
                role="menuitem"
              >
                <LogOut size={13} />
                <span>Sign Out</span>
              </button>
            </div>
          ) : (
            <div className="userDropdownInfoNote">
              <p>Azure Easy Auth is active when deployed to App Service.</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
